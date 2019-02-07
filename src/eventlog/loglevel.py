from logging import addLevelName
from .event_pb2 import LogLevel, NOTSET, TRACE, DEBUG, INFO, OK,\
    WARNING, ERROR, CRITICAL, EXTREME


def registerExtraLevels():
    # register nonstandard levels with python logging
    addLevelName(TRACE, 'TRACE')
    addLevelName(EXTREME, 'EXTREME')
    addLevelName(OK, 'OK')


__all__ = [
    LogLevel,
    NOTSET,
    TRACE,
    DEBUG,
    INFO,
    OK,
    WARNING,
    ERROR,
    CRITICAL,
    EXTREME,
    registerExtraLevels,
]
