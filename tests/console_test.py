import unittest

from eventlog import Event, EventLogger, ConsoleEventLogger, formatTstampAsMillis
from logging import getLogger, DEBUG, INFO

def viewResource(resourceId):
    return Event('resource_view', target=resourceId)

def editResource(resourceId, comment=None):
    return Event('resource_edit', target=resourceId, message=comment)

class ConsoleLogTest(unittest.TestCase):

    def setUp(self):
        self.consoleLogger = ConsoleEventLogger()
        # format timestamps as milliseconds
        #self.consoleLogger.addFilter(formatTstampAsMillis)

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

        ev2 = editResource('my-workbook', comment="added table of contents")
        self.consoleLogger.logEvent(ev2)
        
