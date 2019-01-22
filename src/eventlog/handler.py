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
        self.altLogger = None

    # add event to queue for sending to log forwarder
    # queue is persistent locally (via sqlite) so this should work
    # even if the log forwarder is down briefly.
    # All events passed are logged,
    # regardless of the logging level of the handler
    def logEvent(self, event):
        if self._enable:
            data = self.serialize(event.toDict())
            self._logData(data)

        # if an alt logger has been set up, copy logs there
        # if the alt logger throws an exception, it will block this logger
        if self.altLogger:
            self.altLogger.logEvent(event)

    # Internal method that logs byte stream
    def _logData(self, data):

        # on first send, set up worker thread and network transport
        self._setup_transport()
        self._start_worker_thread()

        try:
            AsynchronousLogHandler._worker_thread.enqueue_event(data)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            # If event can't be sent to logstash, worker thread writes to sqlite.
            # This ex should only occur if write to sqlite (on local filesystem) failed,
            # or if there's some other bug in this package
            if sys.stderr:
                sys.stderr.write("\n\n--- logEvent FAIL. Event not logged ---\n")
                sys.stderr.write(data)
                sys.stderr.wrtie('\n')
                t, v, tb = sys.exc_info()
                traceback.print_exception(t, v, tb, None, sys.stderr)

    # override emit to make everything go through logEvent
    def emit(self, record):
        if not self._enable:
            return  # we should not do anything, so just leave
        event = LogRecordEvent(record)
        self.logEvent(event)

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

    # add secondary logger (usually a ConsoleEventLogger)
    def copyLogsTo(self, altLogger):
        # catch accidental loops (at 0 or 1-deep)
        if altLogger is None or altLogger == self or altLogger.altLogger == self:
            raise Exception("Invalid parameter. Loops not allowed.")
        self.altLogger = altLogger


# LoggingValue can be used as a Counter or Gauge
# that logs events for all changes to its value
# It can be initialized with template event fields (target,fields)
# that are used for generated events
class _LoggingValue(object):

    # Create a Logging value that will log all changes to its state
    # @param eventLogger - how the event will be logged
    # @param target - message target, used in all subsequent events
    # @param initialValue - initial value of counter
    # @param fields - initial set of fields that will be applied
    #            to all subsequent events, unless overridden by
    #            the 'params' field of an inc() or set() invocation
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

    # Set a new value and log it, with optional additional parameters.
    # The Event is generated from the target and default fields from the
    # constructor, plus the value, new params, message and level
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
        self.eventLogger.logEvent(e)

    # Increment Counter
    # @param delta amount to increment, default 1
    # @param params optional additional fields to log in event.fields
    # @param message optional message
    def inc(self, delta=1, params={}, message=None):
        self.set(self.value + delta, params=params, message=message)

    # Returns reference to the internal fields
    # Fields may be adjusted by caller. It is caller's responsibility
    # to ensure thread safety for modifications to the fields dict
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
_CONSOLE_LINE1_FORMAT = "{tstamp:<12} {level:<5} {name}:{target} ({value}) {message}"
_CONSOLE_LINE2_FORMAT = ' ' * 34 + "{host}.{pid} {code} {other}"
# Any event fields not listed here will be included in 'other'
_not_other = ('code', 'codeFile', 'codeFunc', 'codeLine', 'host', 'level',
              'message', 'name', 'pid', 'target', 'tstamp', 'value', 'version')


# format for compact and human readable console output
# @param line1Format format string for console output line 1
# @param line2Format format string for line 2
# only line 1 is generated if line 2 is blank
# @param delim newline delimeter
def format_console(evDict, line1Format, line2Format, delim=b'\n'):
    p = copy(evDict)  # copy dict so we don't modify evDict param
    keys = set(p.keys())

    # fix tstamp to show seconds + %.3f millis
    # if integer already, leave as-is
    ts = p["tstamp"]
    p["tstamp"] = math.floor(ts * 1000) / 1000 if isinstance(ts, float) else ts
    # convert level (int) to string name
    p["level"] = LogLevel.toString(p["level"])
    # replace None with empty string
    for f in ('value', 'target', 'message'):
        if p.get(f, None) is None:
            p[f] = ""
    # meta-field "code" combines func, file, lineo
    file = p.get("codeFile", "")
    func = p.get("codeFunc", "")
    lineNo = str(p.get("codeLine", ""))
    if file and lineNo:
        p["code"] = "%s|%s@%s" % (func, os.path.basename(file), lineNo)
    else:
        p["code"] = ""

    # remove fields used in line 1 to determine 'other' for line 2
    other = keys.difference(_not_other)
    p['other'] = print_dict({k: p[k] for k in other})

    # generate line1 and, if non-blank, line 2
    line1 = line1Format.format(**p)
    line2 = line2Format.format(**p)
    out = line1 + delim + line2 if line2.strip() else line1
    # console writer adds final \n
    return out


# log to console (or a writable stream) instead of sending to logstash
# also doesn't create worker thread
class ConsoleEventLogger(EventLogger):

    def __init__(self, ch=sys.stdout, delim=b'\n',
                 line1Format=_CONSOLE_LINE1_FORMAT,
                 line2Format=_CONSOLE_LINE2_FORMAT):
        self.delim = delim.decode() if six.PY3 and isinstance(delim, bytes) else delim
        super(ConsoleEventLogger, self).__init__(
            host='', port=0,
            serialize=lambda ed: format_console(ed, line1Format, line2Format, self.delim))
        self.ch = ch

    # overriding _logData prevents asynchronous sending
    # write a buffer to output channel and terminate with newline
    def _logData(self, buf):
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
