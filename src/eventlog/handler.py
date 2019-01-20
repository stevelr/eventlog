import logging
import sys
import traceback
from copy import copy

import six

from log_async.handler import AsynchronousLogHandler

from .config import getConfigSetting
from .event import Event, LogRecordEvent
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
    def set(self, value, params={}, message=None):
        f = copy(self.fields)
        self.value = value
        for k, v in six.iteritems(params):
            f[k] = v
        e = Event(self.name,
                  self.target,
                  value=value,
                  fields=f,
                  message=message)
        self.logEvent(e)

    def inc(self, delta=1, params={}, message=None):
        self.set(self.value + 1, params=params, message=message)

    # Returns reference to the internal fields
    def fields(self):
        return self.fields


# log to console (or a writable stream) instead of sending to logstash
# also doesn't create worker thread
# TODO: a non-json serializer would be more readable
class ConsoleEventLogger(EventLogger):

    def __init__(self, ch=sys.stdout, delim=b'\n'):
        super(ConsoleEventLogger, self).__init__(
            host='', port=0,
            serialize=getSerializer())
        self.ch = ch
        self.delim = delim
        if six.PY3:
            if isinstance(delim, bytes):
                self.delim = delim.decode()

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
