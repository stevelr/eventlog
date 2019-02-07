# eventlog package

from .config import getConfigSetting, initMiddleware
from .event import makeMessage, newEvent
from .handler import ConsoleEventHandler, EventFormatter,\
    EventHandler, format_console
from .proto import formatTstampAsMillis, formatTstampAsNanos
from .transport import NetTransport

__version__ = "0.9.200"  # keep in sync with ../../setup.py


# internal global for default loger
_systemDefaultEventHandler = None


# Return system default event logger, creating it if necessary
# Uses configuration provided by environment variables
def defaultEventHandler():
    handler = _systemDefaultEventHandler
    if handler is None:
        # If connection fails, this throws an exception
        # If environment not setup up, returns None, so fall thru
        # to create ConsoleEventHandler
        transport = NetTransport.createFromEnv()
        if transport is not None:
            handler = EventHandler(transport=transport)
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
    makeMessage,
    newEvent,

    # handler
    ConsoleEventHandler,
    EventFormatter,
    EventHandler,
    format_console,

    # proto
    formatTstampAsMillis,
    formatTstampAsNanos,
]
