import logging
import math
import os
import sys
import traceback
from copy import copy

import six

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


# EventHandler sends events over the network via a Transport
#
#    In addition to sending regular events with the logEvent() method,
#    this class also works as a logging handler (with logger.addHandler()
#    to send standard python log messages as events.
#
#    Events generated through logger.{info,debug,...} only generate and
#    transmit events if the logger is enabled for events at that level.
#    Events sent through logEvent() are logged always, regardless
#    of the logger's level.
#
#    EventHandler may have a replica, which receives a copy of all events.
#    This is similar to the concept of logging.addHandler(), except that replica
#    works for all events, not just python logging records.
#
#    An optional fallback transport may be provided in case the
#    primary transport fails. For complete recovery, the fallback transport
#    should be accompanied by scripts or other mechanism to forward
#    archived events over the network once primary transport is restored.
#    In addition, if fallback transport is disk-based, or memory-based,
#    care should be taken to prevent filling disk or memory.
class EventHandler(logging.Handler):

    # Initialize EventHandler
    # @param serialize function for turning event into byte stream
    # @param transport method of sending events to remote logger
    # @param replica optional handler for sending copies of events
    #        (for example, to send to console)
    # @param fallbackTx optional fallback transport in case primary tx
    #        fails to send
    def __init__(self, serialize, transport,
                 replica=None, fallbackTx=None):
        super(EventHandler, self).__init__()
        self.serialize = serialize or getSerializer()
        self.formatter = EventFormatter(self.getSerializer)
        self.transport = transport
        self.replica = replica
        self.fallbackTx = fallbackTx

    # add event to queue for sending to log forwarder
    # queue is persistent locally (via sqlite) so this should work
    # even if the log forwarder is down briefly.
    # If either primary or replica transport hangs, it will block
    # the current thread.
    def logEvent(self, event):
        data = self.serialize(event.toDict())
        self._sendData(data)

        # if a replica handler has been set up, copy logs there
        if self.replica:
            self.replica.logEvent(event)

    # send byte stream through transport
    # Internal method that logs byte stream
    def _sendData(self, data):

        try:
            self.transport.send([data, ])
        except Exception:
            sys.stderr.write("ERROR - Primary event transport failed, using fallback\n")
            try:
                # if fallback fails, then throw new exception
                self.fallbackTx.send([data, ])
            except Exception:
                sys.stderr.write("CRITICAL - Fallback event transport failed\n")
                sys.stderr.write(data)
                t, v, tb = sys.exc_info()
                traceback.print_exception(t, v, tb, None, sys.stderr)
                raise

    # override emit to make everything go through logEvent
    def emit(self, record):
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

    # add secondary handler (usually a ConsoleEventHandler)
    # if parameter is None, disables secondary handler
    def setReplica(self, replica):
        # catch accidental loops (at 0 or 1-deep)
        if replica is not None:
            if replica == self or replica.replica == self:
                raise Exception("Invalid parameter. Loops not allowed.")
        self.replica = replica

    def setFallbackTransport(self, fallback):
        if fallback is not None and fallback == self.fallbackTx:
            raise Exception("Fallback transport may not be the same as primary")
        self.fallbackTx = fallback


# LoggingValue can be used as a Counter or Gauge
# that logs events for all changes to its value
# It can be initialized with template event fields (target,fields)
# that are used for generated events
class _LoggingValue(object):

    # Create a Logging value that will log all changes to its state
    # @param EventHandler - how the event will be logged
    # @param target - message target, used in all subsequent events
    # @param initialValue - initial value of counter
    # @param fields - initial set of fields that will be applied
    #            to all subsequent events, unless overridden by
    #            the 'params' field of an inc() or set() invocation
    def __init__(self,
                 eventHandler,
                 name,
                 target='',
                 initialValue=0,
                 fields={}
                 ):
        self.eventHandler = eventHandler
        self.name = name
        self.target = target
        self.value = initialValue
        self.fields = fields

    # Set a new value and log it, with optional additional parameters.
    # The Event is generated from the target and default fields from the
    # constructor, plus the value, new params, message and level.
    # The event is transmitted regardless of information level; level is
    # intended to be used for downstream filtering and alerting.
    # @param value should be numeric or string.
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
        self.eventHandler.logEvent(e)

    # get returns the current value of the counter or gauge
    def get(self):
        return self.value

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
class ConsoleEventHandler(EventHandler):

    def __init__(self, ch=sys.stdout, delim=b'\n',
                 line1Format=_CONSOLE_LINE1_FORMAT,
                 line2Format=_CONSOLE_LINE2_FORMAT):
        self.delim = delim.decode() if six.PY3 and isinstance(delim, bytes) else delim
        super(ConsoleEventHandler, self).__init__(
            serialize=lambda ed: format_console(ed, line1Format, line2Format, self.delim),
            transport=None
        )
        self.ch = ch

    # overriding _logData prevents asynchronous sending
    # write a buffer to output channel and terminate with newline
    def _sendData(self, buf):
        if six.PY3 and isinstance(buf, bytes):
            self.ch.write(buf.decode())
        else:
            self.ch.write(buf)
        self.ch.write(self.delim)
