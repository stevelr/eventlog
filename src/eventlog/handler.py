import logging
import math
import os
import sys
import traceback
from copy import copy

import six

from log_async.handler import AsynchronousLogHandler

from .config import getConfigSetting
from .event import Event, LogLevel, LogRecordEvent
from .proto import getSerializer


# EventFormatter - turns a python logging record into an Event and formats it
class EventFormatter(logging.Formatter):

    # @param getSerializer - function
    # that returns a serializer function,
    # which flattens event to byte array (or string in py2)
    # The Serializer is often tied to the network protocol
    # (fluentd uses a msgpack serializer, etc.)
    # if None, the default formatter (json) will be used
    def __init__(self, getSerializerFn=None):
        self.getSerializerFn = getSerializerFn or (lambda: getSerializer())

    def format(self, record):
        e = LogRecordEvent(record).toDict()
        return self.getSerializerFn()(e)


# EventLogger sends events to a forwarding server,
#        after queuing them in a local sqlite database.
#        The sqlite database ensures that events are logged even if the
#        forwarding server process is temporarily unavailable.
#
#    In addition to sending regular events with the logEvent() method,
#    this class also works as a logging handler (with logger.addHandler()
#    to send standard python log messages as events.
#
#    Events generated through logger.{info,debug,...} only generate and
#    transmit events if the logger is enabled for events at that level.
#    Events sent through logEvent() are logged always, regardless
#    of the logger's level.
class EventLogger(AsynchronousLogHandler):

    def __init__(self, *args, **kwargs):
        ser = kwargs.pop('serialize') or getSerializer()
        super(EventLogger, self).__init__(*args, **kwargs)
        self.serialize = ser
        self.formatter = EventFormatter(self.getSerializer)

    # add event to queue for sending to logstash
    # queue is persistent locally (via sqlite) so this should work
    # even if logstash is down briefly.
    # All events passed are logged,
    # regardless of the logging level of the handler.
    #
    # param e: a subclass of Event
    #
    def logEvent(self, event):

        stream = self.serialize(event.toDict())
        self._setup_transport()
        self._start_worker_thread()

        try:
            AsynchronousLogHandler._worker_thread.enqueue_event(stream)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            # If event can't be sent to logstash, worker thread writes to sqlite.
            # This ex should only occur if write to sqlite (on local filesystem) failed,
            # or if there's some other bug in this package
            if sys.stderr:
                sys.stderr.write("\n\n--- logEvent FAIL. Event not logged ---\n")
                sys.stderr.write(stream)
                sys.stderr.wrtie('\n')
                t, v, tb = sys.exc_info()
                traceback.print_exception(t, v, tb, None, sys.stderr)

    # Create a Counter/Gauge value that logs all changes.
    def createTrackingValue(self, name, target, initialValue=0, fields={}):
        return _LoggingValue(self, name, target, initialValue, fields)

    def getSerializer(self):
        return self.serialize

    def setSerializer(self, ser):
        self.serialize = ser

    # add a filter function to process event objects
    # before they are serialized. A filter function
    # takes dictionary and returns the processed dictionary.
    # Filters can be cascaded.
    def addFilter(self, filter):
        ser = self.getSerializer()
        new_ser = lambda evDict: ser(filter(evDict))
        self.setSerializer(new_ser)


class _LoggingValue(object):
    # Create a Logging value that will log all changes to its state
    # @param eventLogger - how the event will be logged
    # @param logInit - set to true if you want the construction logged
    def __init__(self,
                 eventLogger,
                 name,
                 target='',
                 initialValue=0,
                 fields={}
                 ):
        self.eventLogger = eventLogger
        self.name = name
        self.target = target
        self.value = initialValue
        self.fields = fields

    def makeEvent(self, message=None):
        e = Event(name=self.name,
                  target=self.target,
                  value=self.value,
                  message=message,
                  fields=self.fields)
        return e

    def logEvent(self, e):
        self.eventLogger.logEvent(e)

    # log value, with optional additional parameters
    # the full set of parameters will be the defaultFields
    # initialized in the constructor, with params added on.
    # the inherent fields are not modified
    def set(self, value, params={}, message=None, level=LogLevel.INFO):
        f = copy(self.fields)
        self.value = value
        for k, v in six.iteritems(params):
            f[k] = v
        e = Event(self.name,
                  self.target,
                  level=level,
                  value=value,
                  fields=f,
                  message=message)
        self.logEvent(e)

    def inc(self, delta=1, params={}, message=None):
        self.set(self.value + 1, params=params, message=message)

    # Returns reference to the internal fields
    def fields(self):
        return self.fields


# returns compact display of dict for human readability
def print_dict(d):
    s = ''
    for k in sorted(d.keys()):
        val = d[k]
        val = isinstance(val, dict) and ('{' + print_dict(val) + '}') or str(val)
        s = s + k + ':' + val + ' '
    return s[:-1]  # remove trailing space


# default format for line 1 format
# omitted: loc,host,pid {loc}{host}.{pid}
_CONSOLE_LINE1_FORMAT = "{tstamp:<12} {name:<15} {level} v:{value} t:{target} m:{message}"


_CONSOLE_LINE2_INDENT = 30


# format for compact and human readable console output
# @param line1Format format string for console output
# @param delim newline delimeter
def format_console(evDict, line1Format, delim=b'\n'):
    p = copy(evDict)  # copy dict so this fn is non-destructive
    line2_indent = ' ' * _CONSOLE_LINE2_INDENT
    # compute first line display
    l1 = {}
    # fix tstamp to show milliseconds (sec.000)
    ts = p.pop("tstamp")
    l1["tstamp"] = math.floor(ts * 1000) / 1000 if isinstance(ts, float) else ts
    target = p.pop("target", "")
    l1["target"] = target is not None and str(target) or ""
    l1["level"] = LogLevel.toString(p.pop("level"))
    for k in ("host", "pid", "site", "cluster", "message", "name", "value"):
        l1[k] = p.pop(k, "")
    l1["loc"] = (l1["site"] or l1["cluster"]) and "{site}.{cluster}." or ""
    disp = line1Format.format(**l1)
    p.pop("version")  # don't log version
    file = p.pop("codeFile", "")
    func = p.pop("codeFunc", "")
    lineNo = str(p.pop("codeLine", ""))
    if file and lineNo:
        p["code"] = "%s|%s|%s" % (os.path.basename(file), func, lineNo)
    if p:
        # if any more fields, add second line
        line2 = line2_indent + print_dict(p)
        disp = disp + delim + line2
    return disp


# log to console (or a writable stream) instead of sending to logstash
# also doesn't create worker thread
class ConsoleEventLogger(EventLogger):

    def __init__(self, ch=sys.stdout, delim=b'\n', line1Format=_CONSOLE_LINE1_FORMAT):
        self.delim = delim.decode() if six.PY3 and isinstance(delim, bytes) else delim
        super(ConsoleEventLogger, self).__init__(
            host='', port=0,
            serialize=lambda ed: format_console(ed, line1Format, self.delim))
        self.ch = ch

    # override emit to prevent asynchronous behavior
    def emit(self, record):
        evDict = LogRecordEvent(record).toDict()
        data = self.serialize(evDict)
        self.writeln(data)

    def logEvent(self, event):
        data = self.serialize(event.toDict())
        self.writeln(data)

    # write a buffer to output channel and terminate with newline
    def writeln(self, buf):
        if six.PY3 and isinstance(buf, bytes):
            self.ch.write(buf.decode())
        else:
            self.ch.write(buf)
        self.ch.write(self.delim)


# internal global for default loger
_systemDefaultAsyncLogger = None


# Return system default async event logger, creating it if necessary
# Uses configuration provided by environment variables
def defaultAsyncLogger():
    global _systemDefaultAsyncLogger
    if _systemDefaultAsyncLogger is None:
        logHost = getConfigSetting('EVENTLOG_HOST')
        streamFmt = getConfigSetting('EVENTLOG_FORMAT')
        serialize = getSerializer(streamFmt)

        if logHost == 'console' or not logHost:
            # If logstash connection properties are not set,
            # events will log to the console
            logger = ConsoleEventLogger()
        else:
            logPort = getConfigSetting('EVENTLOG_PORT')
            logPort = logPort and int(logPort) or 5001
            logger = EventLogger(
                host=logHost,
                port=logPort,
                database_path=getConfigSetting('EVENTLOG_DB'),
                serialize=serialize)
        _systemDefaultAsyncLogger = logger
    return _systemDefaultAsyncLogger


# convenience function
def logEvent(e):
    defaultAsyncLogger().logEvent(e)
