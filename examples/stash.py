import os
from eventlog import Event,EventLogger, logEvent, defaultAsyncLogger
from logging import getLogger, DEBUG, INFO

# you may find it useful to define helper functions
# for creating common event types
def viewResource(resourceId):
    return Event('view', resourceId, 'res')

def editResource(resourceId, comment=None):
    return Event('edit', resourceId, 'res', message=comment)


# typical logging setup in python source file
log = getLogger('example')
log.addHandler(asyncEventLogger)
log.setLevel(DEBUG)


def somecode():
    # ...
    log.info("an information message")
    #log.debug("a debug message")


def someevent():
    # current user viewed a resource 'alice-in-wonderland'
    logEvent(viewResource('alice-in-wonderland'))

somecode()
#someevent()
