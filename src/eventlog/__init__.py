# eventlog package

from .config import getConfigSetting, initMiddleware
from .event import Event, LogLevel
from .handler import ConsoleEventHandler, EventFormatter,\
    EventHandler, format_console
from .proto import formatTstampAsMillis, formatTstampAsNanos, getSerializer
from .transport import MAX_MESSAAGE_LEN, MAX_SEND_ATTEMPTS,\
    NetTransport, TCPSocketFactory

__version__ = "0.9.102"  # keep in sync with ../../setup.py


# internal global for default loger
_systemDefaultEventHandler = None


# Return system default event logger, creating it if necessary
# Uses configuration provided by environment variables
def defaultEventHandler():
    handler = _systemDefaultEventHandler
    if handler is None:
        streamFmt = getConfigSetting('EVENTLOG_FORMAT')
        serialize = getSerializer(streamFmt)

        # If connection fails, this throws an exception
        # If environment not setup up, returns None, so fall thru
        # to create ConsoleEventHandler
        transport = NetTransport.createFromEnv()
        if transport is not None:
            handler = EventHandler(serialize=serialize, transport=transport)
        else:
            handler = ConsoleEventHandler()
        setDefaultEventHandler(handler)
    return handler


# override default system handler
def setDefaultEventHandler(h):
    global _systemDefaultEventHandler
    _systemDefaultEventHandler = h


# convenience function
def logEvent(e):
    defaultEventHandler().logEvent(e)


__all__ = [

    __version__,
    defaultEventHandler,
    logEvent,
    setDefaultEventHandler,

    # config
    getConfigSetting,
    initMiddleware,

    # event
    Event,
    LogLevel,

    # handler
    ConsoleEventHandler,
    EventFormatter,
    EventHandler,
    format_console,

    # proto
    formatTstampAsMillis,
    formatTstampAsNanos,
    getSerializer,

    # transport
    MAX_MESSAAGE_LEN,
    MAX_SEND_ATTEMPTS,
    NetTransport,
    TCPSocketFactory,
]
