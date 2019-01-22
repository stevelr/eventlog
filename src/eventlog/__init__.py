# eventlog package

from .config import getConfigSetting, initMiddleware
from .event import Event, LogLevel
from .handler import ConsoleEventLogger, defaultAsyncLogger,\
    EventFormatter, EventLogger, format_console, logEvent
from .proto import formatTstampAsMillis, formatTstampAsNanos, getSerializer

__version__ = "0.9.101"  # keep in sync with ../../setup.py

__all__ = [

    __version__,

    # event
    Event,
    LogLevel,

    # handler
    ConsoleEventLogger,
    defaultAsyncLogger,
    EventFormatter,
    EventLogger,
    format_console,
    logEvent,

    # proto
    formatTstampAsMillis,
    formatTstampAsNanos,
    getSerializer,

    # config
    getConfigSetting,
    initMiddleware,
]
