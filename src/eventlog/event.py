import os
import socket
import sys
import time
import traceback
from copy import copy

import six

from .config import _getUserContext, getConfigSetting

try:
    import ujson as json
except ImportError:
    import json


class LogLevel:
    TRACE = -4
    DEBUG = -3
    NOTSET = -2          # value when level is not specified
    INFO = -1            # informational message, no error condition
    OK = 0               # status: systems operating normally
    WARNING = WARN = 1   # warning condition, may need attention
    ERROR = ERR = 2      # error condition, not operating normally
    CRITICAL = CRIT = 3  # system critical
    EXTREME = 4          # more urgent than critical

    MIN_VALUE = TRACE
    MAX_VALUE = EXTREME


class Event(object):

    # static variables calculated once and cached
    host = socket.gethostname()
    version = 1
    pid = os.getpid()
    # site and cluster can be defined in environment or settings
    # (if both, environment takes precedence)
    # if neither, an error message is printed
    site = getConfigSetting('EVENTLOG_SITE')
    cluster = getConfigSetting('EVENTLOG_CLUSTER')

    '''tsunits - global setting for timestamp units.
       Time is stored in the event log as a floating point number of seconds.
       When exported, they can be converted to either milliseconds or nanoseconds

       Options are "sec": time is a floating point number of seconds,
                   "ms": time is an integer point number of milliseconds,
                   "ns": time is an integer number of nanoseconds
        Default is "ms" '''
    tsunits = getConfigSetting('EVENTLOG_UNITS')

    '''Eventlog constructor
       @param name the event name
       @param target reference to object of event
       @param value a value (int/float/string) representing the object's value.
              Often used for counters, gauges, etc.
       @param level the debug level (see eventlog.LogLevel)
       @param message a string message or comment to be stored with the event
       @param fields a dictionary of key/value pairs,
              for example, other dimensions or labels for the event
       @param logFrame if true, also collect info about code location
              (file, function, line number)

       In addition to these parameters, the event stores the current timestamp,
       (a float, in seconds since EPOCH),
       optional server/site info,
       http request info such as current user, request url, etc
       (if used within django or http server)
    '''
    def __init__(self,
                 name,
                 target,
                 value=0,
                 level=LogLevel.NOTSET,
                 message=None,
                 fields=None,
                 logFrame=False,
                 ):

        self.name = name
        self.tstamp = time.time()     # float seconds
        self.version = Event.version
        self.host = Event.host
        self.site = Event.site
        self.cluster = Event.cluster
        self.pid = Event.pid
        self.target = target
        self.message = message
        self.value = value
        self.codeFile = None
        self.codeLine = 0
        self.codeFunc = None
        self.fields = None

        self.setLevel(level)

        if logFrame:
            self.addCodeFrame()

        # collect user context, if middleware hook is installed
        if _getUserContext:
            self.reqId, self.user, self.session = _getUserContext()

        if fields:
            self.addFields(fields)

    def printFrame(self, f):
        print("file: ", f.f_code.co_filename,
              "line: ", f.f_code.co_firstlineno, f.f_lineno,
              "name: ", f.f_code.co_name)

    def setLevel(self, level):
        if isinstance(level, six.integer_types):
            self.level = level
        elif isinstance(level, six.string_types):
            self.level = LogLevel.__dict__[level.upper()]
        else:
            raise Exception("Invalid level: " + str(level))
        if self.level < LogLevel.MIN_VALUE or self.level > LogLevel.MAX_VALUE:
            raise Exception("Level out of range: %d" % self.level)

    '''addTags adds a list of string tags to the event.
       Tags are modeled as fields, with field_name=label, value=1
    '''
    def addTags(self, tags):
        self.addFields({t: 1 for t in tags})

    '''addFields adds fields to the event.
       @param fields - dict of key-value pairs
    '''
    def addFields(self, fields):
        if not self.fields:
            self.fields = {}
        for (k, v) in six.iteritems(fields):
            self.fields[k] = v

    '''addLabels adds a set of label/value pairs (alias for addFields)'''
    def addLabels(self, labels):
        self.addFields(labels)

    # get file and lineno of caller from stack frame
    def addCodeFrame(self):
        try:
            frame = sys._getframe(3)
        except Exception:
            return
        while frame:
            fname = frame.f_code.co_filename
            if fname.endswith('logging/__init__.py') \
                     or '/eventlog' in fname \
                     or 'logstash_async' in fname:
                frame = frame.f_back
            else:
                break
        self.codeFile = frame.f_code.co_filename
        self.codeLine = frame.f_lineno
        self.codeFunc = frame.f_code.co_name

    # returns a dictionary containing all the event fields
    # extra fields are in "fields"
    def toDict(self):
        return copy(self.__dict__)


# LogRecordEvent - an Event wrapper around a python logging Record
class LogRecordEvent(Event):

    def __init__(self, record):
        super(LogRecordEvent, self).__init__(
            name='python_log',
            target='logger:' + record.name,
            level=record.levelname,
            message=record.getMessage(),
            fields={'level': record.levelname.lower()},
            logFrame=True,
        )
        if record.created:
            self.tstamp = record.created
        tags = getattr(record, 'tags', [])
        if tags:
            self.addTags(tags)
        extra = getattr(record, 'extra', {})
        if extra:
            self.addFields(extra)
        if getattr(record, 'exc_info', None) is not None:
            (excType, val, tb) = record.exc_info
            tbdata = traceback.extract_tb(tb)
            self.addFields({
                'exc_info': json.dumps((excType, val, tbdata)),
            })
            if self.level == LogLevel.NOTSET:
                self.level = LogLevel.ERROR
