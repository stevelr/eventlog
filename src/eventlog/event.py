import os
import socket
import sys
import time
import traceback

import six
from .config import _getUserContext, getConfigSetting

try:
    import ujson as json
except ImportError:
    import json

_EVENT_SCHEMA_VERSION = 0.9  # major.minor


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

    @staticmethod
    def toString(level):
        _val2str = {
            LogLevel.TRACE: "TRACE",
            LogLevel.DEBUG: "DEBUG",
            LogLevel.NOTSET: "_",
            LogLevel.INFO: "INFO",
            LogLevel.OK: "OK",
            LogLevel.WARN: "WARNING",
            LogLevel.ERROR: "ERROR",
            LogLevel.CRITICAL: "CRITICAL",
            LogLevel.EXTREME: "EXTREME",
        }
        return _val2str.get(level, "")

    # returns integer log level from name, e.g., "DEBUG" returns 3
    # if not found, returns KeyError
    @staticmethod
    def valueOf(levelName):
        try:
            return getattr(LogLevel, levelName.upper())
        except AttributeError:
            raise KeyError(levelName, "Invalid log level")


class Event(object):

    # static variables calculated once and cached
    host = socket.gethostname()
    version = _EVENT_SCHEMA_VERSION
    pid = os.getpid()
    # site and cluster can be defined in environment or settings
    # (if both, environment takes precedence)
    # if neither, an error message is printed
    site = getConfigSetting('EVENTLOG_SITE')
    cluster = getConfigSetting('EVENTLOG_CLUSTER')

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
                 value=None,
                 level=LogLevel.NOTSET,
                 message=None,
                 fields=None,
                 logFrame=False,
                 ):
        self._d = {
            'name': name,
            'tstamp': time.time(),
            'version': Event.version,
            'host': Event.host,
            'pid': Event.pid,
            'level': self.validateLevel(level),
        }

        self.setIfNN('site', Event.site)
        self.setIfNN('cluster', Event.cluster)
        self.setIfNN('target', target)
        self.setIfNN('message', message)
        self.setIfNN('value', value)

        if logFrame:
            self.addCodeFrame()

        # collect user context, if middleware hook is installed
        if _getUserContext:
            reqId, user, ses = _getUserContext()
            self.set('reqId', reqId)
            self.set('user', user)
            self.set('session', ses)

        if fields:
            self.addFields(fields)

    def printFrame(self, f):
        print("file: ", f.f_code.co_filename,
              "line: ", f.f_code.co_firstlineno, f.f_lineno,
              "name: ", f.f_code.co_name)

    def validateLevel(self, level):
        if isinstance(level, six.integer_types):
            lv = level
        elif isinstance(level, six.string_types):
            lv = LogLevel.valueOf(level)
        else:
            raise Exception("Invalid level: " + str(level))
        if lv < LogLevel.MIN_VALUE or lv > LogLevel.MAX_VALUE:
            raise Exception("Level out of range: %d" % lv)
        return lv

    '''addTags adds a list of string tags to the event.
       Tags are modeled as fields, with field_name=label, value=1
    '''
    def addTags(self, tags):
        self.addFields({t: 1 for t in tags})

    '''addFields adds fields to the event.
       @param fields - dict of key-value pairs
    '''
    def addFields(self, fields):
        try:
            fmap = self._d['fields']
        except KeyError:
            fmap = {}
            self.set('fields', fmap)
        for (k, v) in six.iteritems(fields):
            fmap[k] = v

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
        self.set('codeFile', frame.f_code.co_filename)
        self.set('codeLine', frame.f_lineno)
        self.set('codeFunc', frame.f_code.co_name)

    # returns a dictionary containing all the event fields
    # extra fields are in "fields"
    def toDict(self):
        return self._d

    def set(self, key, val):
        self._d[key] = val

    def setIfNN(self, key, val):
        if val is not None:
            self._d[key] = val


# LogRecordEvent - an Event wrapper around a python logging Record
class LogRecordEvent(Event):

    def __init__(self, record):
        super(LogRecordEvent, self).__init__(
            name='python_log',
            target='logger:' + record.name,
            level=record.levelname,
            message=record.getMessage(),
            logFrame=True,
        )
        if record.created:
            self.set('tstamp', record.created)
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
            if self._d == LogLevel.NOTSET:
                self.set('level', LogLevel.ERROR)
