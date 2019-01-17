
from eventlog import Event, EventLogger, ConsoleEventLogger
from logging import getLogger, DEBUG, INFO

def viewResource(resourceId):
    return Event('resource_view', resourceId)

def editResource(resourceId, comment=None):
    return Event('resource_edit', resourceId, message=comment)


# ConsoleEventLogger logs json events to stderr.
# It tests the Event processing but does not forward events to logstash
consoleLogger = ConsoleEventLogger()

# typical logging setup in python source file
log = getLogger()
log.addHandler(consoleLogger)
log.setLevel(DEBUG)


# ordinary log messages are routed through this logger
log.info("an information message")
log.debug("a debug message")

# current user viewed a resource 'alice-in-wonderland'
consoleLogger.logEvent(viewResource('alice-in-wonderland'))


