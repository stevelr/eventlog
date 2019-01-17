import unittest

from eventlog import Event, EventLogger, ConsoleEventLogger
from logging import getLogger, DEBUG, INFO

def viewResource(resourceId):
    return Event('resource_view', resourceId)

def editResource(resourceId, comment=None):
    return Event('resource_edit', resourceId, message=comment)

class ConsoleLogTest(unittest.TestCase):

    def setUp(self):
        self.consoleLogger = ConsoleEventLogger()
        log = getLogger()
        log.addHandler(self.consoleLogger)
        log.setLevel(DEBUG)
        self.log = log

    def tearDown(self):
        pass

    def test_full(self):

        self.log.info("an info message")
        self.log.debug("a debug message")

        self.assertTrue(True)

    def test_event(self):
        event = viewResource('alice-in-wonderland')
        self.consoleLogger.logEvent(event)
        self.assertTrue(event is not None)


