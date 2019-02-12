import unittest

from eventlog import newEvent, ConsoleEventHandler
from logging import getLogger


def viewResource(resourceId):
    return newEvent('resource_view', target=resourceId)


def editResource(resourceId, comment=None):
    return newEvent('resource_edit', target=resourceId, message=comment)


class ConsoleLogTest(unittest.TestCase):

    def setUp(self):
        self.consoleHandler = ConsoleEventHandler()

        log = getLogger()
        log.addHandler(self.consoleHandler)
        self.log = log

    def tearDown(self):
        pass

    def test_full(self):
        self.log.debug("a debug message")
        self.log.info("an info message")
        self.log.warning("a warning message")
        self.log.critical("a critical messase")
        self.assertTrue(True)

    def test_event(self):
        event = viewResource('alice-in-wonderland')
        self.consoleHandler.logEvent(event)
        self.assertTrue(event is not None)

        ev2 = editResource('my-workbook', comment="added table of contents")
        self.consoleHandler.logEvent(ev2)
