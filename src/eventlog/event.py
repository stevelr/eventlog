import os
import random
import six
import socket
import sys
import time
import traceback

from .loglevel import INFO, NOTSET, OK
from .event_pb2 import DeployType, EventHeader, Extra, Event, LogLevel
from google.protobuf.json_format import MessageToJson

from .config import _getUserContext, getConfigSetting
from .counter import AtomicCounter

try:
    import ujson as json
except ImportError:
    import json


_EVENT_SCHEMA_VERSION = (0, 1)

# _isnumeric returns True if parameter is a numeric type (int, long, float)
_isnumeric = lambda x: isinstance(x, six.integer_types) or isinstance(x, float)


class EventSettings(object):

    # static variables calculated once and cached
    host = socket.gethostname()
    pid = os.getpid()
    # client, datactr and cluster can be defined in environment or settings
    # (if both, environment takes precedence)
    # if neither, an error message is printed
    client = getConfigSetting('EVENTLOG_CLIENT') or u''
    datactr = getConfigSetting('EVENTLOG_DATACTR') or u''
    cluster = getConfigSetting('EVENTLOG_CLUSTER') or u''
    deploy = getConfigSetting('EVENTLOG_DEPLOY') or DeployType.Value('PROD')

    # idgen creates a unique event id within this VM/insance.
    # It could be considered globally unique but doesn't need to be.
    # The main purposes are to disambiguate events with the same
    # millisecond timestamp, and to support end-to-end debug tracing
    # It can also be used to measure how many events are generated
    # by each server over a time period
    _idgen = AtomicCounter(random.getrandbits(48))


# newEvent create a new Event
# @param name the event name
# @param target reference to object of event
# @param value a numeric value representing the object's value.
#       Often used for counters, gauges, etc. Defaults to 0
#       Value is converted to float64 in the database.
# @param level the debug level (see eventlog.loglevel)
# @param message a string message or comment to be stored with the event
# @param fields a dictionary of key/value pairs,
#       for example, other dimensions or labels for the event
# @param logFrame if true, also collect info about code location
#       (file, function, line number)
# @param duration is a duration for performance measurements.
#       The value is seconds(float)
#
# In addition to these parameters, the event stores the current timestamp,
# (a float, in seconds since EPOCH),
# optional server/site info,
# http request info such as current user, request url, etc
# (if used within django or http server)
def newEvent(name,
             target,
             value=0,
             level=OK,
             message=None,
             fields=None,
             logFrame=False,
             duration=0,
             ):
    e = Event(
        name=name,
        tstamp=time.time(),
        target=target,
        value=value,
        message=message,
        duration=duration,
        eid=EventSettings._idgen.nextVal(),
    )
    e.log.level = level
    e.server.host = EventSettings.host
    e.server.pid = EventSettings.pid
    e.server.deploy = EventSettings.deploy
    e.server.client = EventSettings.client
    e.server.datactr = EventSettings.datactr
    e.server.cluster = EventSettings.cluster
    e.version.major = _EVENT_SCHEMA_VERSION[0]
    e.version.minor = _EVENT_SCHEMA_VERSION[1]

    if logFrame:
        addCodeFrame(e)

    # collect user context, if middleware hook is installed
    if _getUserContext:
        e.user, e.session = _getUserContext()

    if fields:
        addFields(e, fields)

    return e


def addLabels(e, labels):
    for l in labels:
        e.labels.append(l)


# addFields adds fields to the event.
# @param fields - dict of key-value pairs
def addFields(e, fields):
    e.fields.extend([Extra(key=k, value=v) for k, v in six.iteritems(fields)])


# get file and lineno of caller from stack frame
def addCodeFrame(e):
    try:
        frame = sys._getframe(3)
    except Exception:
        return
    while frame:
        fname = frame.f_code.co_filename
        if fname.endswith('logging/__init__.py') \
                 or '/eventlog' in fname:
            frame = frame.f_back
        else:
            break
    e.log.code_file = frame.f_code.co_filename
    e.log.code_line = frame.f_lineno
    e.log.code_func = frame.f_code.co_name


def eventToJson(e):
    return MessageToJson(e)


def eventToBuffer(e):
    return e.SerializeToString()


def makeMessage(e, category):
    buf = eventToBuffer(e)
    header = EventHeader(
        eid=e.eid,
        tsnano=int(e.tstamp * 1e9),
        category=category,
        msglen=len(buf),
    )
    header.version.major = _EVENT_SCHEMA_VERSION[0]
    header.version.minor = _EVENT_SCHEMA_VERSION[1]
    hbuf = header.SerializeToString()
    return(hbuf, buf)


def newLogRecord(record):
    e = newEvent(name='log',
                 target='logger:' + record.name,
                 level=LogLevel.Value(record.levelname),
                 message=record.getMessage(),
                 logFrame=True)
    if record.created:
        e.tstamp = record.created
    tags = getattr(record, 'tags', [])
    if tags:
        e.addLabels(tags)
    extra = getattr(record, 'extra', {})
    if extra:
        e.addFields(extra)
    if getattr(record, 'exc_info', None) is not None:
        (excType, val, tb) = record.exc_info
        tbdata = traceback.extract_tb(tb)
        e.log.stack_trace = json.dumps((excType, val, tbdata))
    if e.log.level == NOTSET:
        e.log.level = INFO
    return e
