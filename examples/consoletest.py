from eventlog import newEvent, ConsoleEventHandler

from logging import getLogger, DEBUG


def viewResource(resourceId):
    return newEvent(name="resource_view", target=resourceId)


def editResource(resourceId, comment=None):
    return newEvent(name="resource_edit", target=resourceId, message=comment)


# ConsoleEventLogger logs json events to stderr.
# It tests the Event processing but does not forward events to logstash
consoleLogger = ConsoleEventHandler()

# typical logging setup in python source file
log = getLogger()
log.addHandler(consoleLogger)
log.setLevel(DEBUG)


# ordinary log messages are routed through this logger
log.info("an information message")
log.debug("a debug message")

# current user viewed a resource 'alice-in-wonderland'
consoleLogger.logEvent(viewResource('alice-in-wonderland'))
