import unittest

from eventlog import Event, EventHandler, ConsoleEventHandler, formatTstampAsMillis
from logging import getLogger, DEBUG, INFO

def viewResource(resourceId):
    return Event('resource_view', target=resourceId)

def editResource(resourceId, comment=None):
    return Event('resource_edit', target=resourceId, message=comment)

class ConsoleLogTest(unittest.TestCase):

    def setUp(self):
        self.consoleHandler = ConsoleEventHandler()
        # format timestamps as milliseconds
        #self.consoleLogger.addFilter(formatTstampAsMillis)

        log = getLogger()
        log.addHandler(self.consoleHandler)
        self.log = log

    def tearDown(self):
        pass

    def test_full(self):
        self.log.debug("a debug message")
        self.log.info("an info message")
        self.log.warn("a warning message")
        self.log.critical("a critical messase")
        self.assertTrue(True)

    def test_event(self):
        event = viewResource('alice-in-wonderland')
        self.consoleHandler.logEvent(event)
        self.assertTrue(event is not None)

        ev2 = editResource('my-workbook', comment="added table of contents")
        self.consoleHandler.logEvent(ev2)
