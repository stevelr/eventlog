import logging
import os
import sys
import traceback
from copy import copy

import six
import json

from .event import newEvent, newLogRecord, eventToBuffer, eventToJson
from .event_pb2 import INFO


# EventFormatter - turns a python logging record into an Event and formats it
class EventFormatter(logging.Formatter):

    def __init__(self, handler):
        super(EventFormatter, self).__init__()
        self.handler = handler

    def format(self, record):
        e = newLogRecord(record)
        data = self.handler.getSerializer()(e)
        return data


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
    # @param transport method of sending events to remote logger
    # @param serializer method of converting event to buffer
    # @param replica optional handler for sending copies of events
    #        (for example, to send to console)
    # @param fallbackTx optional fallback transport in case primary tx
    #        fails to send
    def __init__(self, transport,
                 serializer=eventToBuffer,
                 replica=None, fallbackTx=None):
        super(EventHandler, self).__init__()
        self.transport = transport
        self.serializer = serializer
        self.formatter = EventFormatter(self)
        self.replica = replica
        self.fallbackTx = fallbackTx

    # add event to queue for sending to log forwarder
    # queue is persistent locally (via sqlite) so this should work
    # even if the log forwarder is down briefly.
    # If either primary or replica transport hangs, it will block
    # the current thread.
    def logEvent(self, event):
        data = self.getSerializer()(event)
        self._sendData(data)

        # if a replica handler has been set up, copy logs there
        if self.replica:
            self.replica.logEvent(event)

    # send byte stream through transport
    # Internal method that logs byte stream
    def _sendData(self, data):
        if six.PY3 and isinstance(data, str):
            data = bytes(data, 'UTF8')

        # if failures occur here, we can't log them because logging itself is failing
        # The final fallback is stderr
        errLog = sys.stderr

        if self.transport.checkStatus():
            try:
                self.transport.send([data, ])
                return
            except Exception:
                if self.fallbackTx:
                    errLog.write("ERROR: Event transport failed, trying fallback\n")
                else:
                    errLog.write("ERROR: Event transport failed and no fallback is defined\n")

        if self.fallbackTx:
            # try fallback, if transport is down or first attempt failed
            try:
                # if fallback fails, then throw new exception
                self.fallbackTx.send([data, ])
            except Exception:
                errLog.write("CRITICAL: Fallback event transport failed\n")
                errLog.write(data)
                t, v, tb = sys.exc_info()
                traceback.print_exception(t, v, tb, None, errLog)
                raise

    # override emit to make everything go through logEvent
    def emit(self, record):
        event = newLogRecord(record)
        self.logEvent(event)

    # Create a Counter/Gauge value that logs all changes.
    def createTrackingValue(self, name, target, initialValue=0, fields={}):
        return _LoggingValue(self, name, target, initialValue, fields)

    def getSerializer(self):
        return self.serializer

    def setSerializer(self, ser):
        self.serializer = ser

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

    # isRemote returns True if there is a network transport,
    # or False if this is a console or file handler
    def isRemote(self):
        return self.transport is not None


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
    def set(self, value, params={}, message=None, level=INFO):
        f = copy(self.fields)
        self.value = value
        for k, v in six.iteritems(params):
            f[k] = v
        e = newEvent(self.name,
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


# default format for console output
_indent = ' ' * 34
_CONSOLE_FORMAT = '''{tstamp:<12} {log_level:<5} {name}:{target} ({value}) {message}
{_indent}{user} {server_host}.{server_pid} {code}
{_indent}{http_remote_addr}'''


# format for compact and human readable console output
# @param textFormat format string for console output
# If there is no data on last rows, they are removed
def format_console(event, textFormat=_CONSOLE_FORMAT):
    p = json.loads(eventToJson(event))
    p['tstamp'] = "%.3f" % p['tstamp']
    for subdict in ('server', 'http', 'log'):
        if subdict in p:
            for k in p[subdict].keys():
                p[subdict + "_" + k] = p[subdict][k]

    # ensure keys used in format string are defined
    for k in ('log_level', 'http_remote_addr', 'http_status', 'message', 'name',
              'server_host', 'server_pid', 'session', 'target', 'user', 'value'):
        if k not in p:
            p[k] = ''

    # meta-field "code" combines func, file, lineo
    file = p.get("log_code_file", "")
    func = p.get("log_code_func", "")
    lineNo = str(p.get("log_code_line", ""))
    if file and lineNo:
        p["code"] = "%s|%s@%s" % (func, os.path.basename(file), lineNo)
    else:
        p["code"] = ""
    p["_indent"] = _indent

    text = textFormat.format(**p)
    text.strip()
    return text


# log to console (or a writable stream) instead of sending to logstash
# also doesn't create worker thread
class ConsoleEventHandler(EventHandler):

    def __init__(self, ch=sys.stdout, textFormat=_CONSOLE_FORMAT):
        super(ConsoleEventHandler, self).__init__(
            transport=None,
            serializer=lambda e: format_console(e, textFormat),
        )
        self.ch = ch

    # overriding _logData prevents asynchronous sending
    # write a buffer to output channel and terminate with newline
    def _sendData(self, buf):
        if six.PY3 and isinstance(buf, bytes):
            self.ch.write(buf.decode())
        else:
            self.ch.write(buf)
        self.ch.write('\n')
