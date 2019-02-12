import six
import unittest

from eventlog import newEvent, EventHandler, ConsoleEventHandler, makeMessage
from logging import getLogger
from eventlog.event_pb2 import Event, EventHeader, HttpMethod
from google.protobuf.json_format import MessageToJson


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

    def test_eid(self):
        e1 = newEvent("alice", "")
        e2 = newEvent("bob", "")
        self.assertEqual(e1.eid + 1, e2.eid)

    # This test tests the serializer,
    # and a handlful of schema fields,
    # and EventHandler.getSerializer()
    def test_serializer(self):
        e = newEvent("MyEvent",
                     "Mytarget",
                     value=17.32,
                     duration=1e-8,
                     message="The rain in Spain"
                     )
        e.server.host = "Hostess"
        e.server.pid = 8080
        e.http.method = HttpMethod.Value('POST')
        e.http.status = 404
        e.http.path = "/some/where"

        # tests EventHandler default Serializer is the protobuf one
        h = EventHandler(transport=None)
        fn = h.getSerializer()
        self.assertTrue(fn is not None)

        # Serialize to buffer
        buf = fn(e)
        if six.PY2:
            self.assertEqual(type(buf), str)
        else:
            self.assertEqual(type(buf), bytes)
        self.assertTrue(len(buf) >= 20)

        # unserialize
        e2 = Event.FromString(buf)
        self.assertTrue(e2 is not None)

        # spot check a couple items
        self.assertEqual(e.name, e2.name)
        self.assertEqual(e2.http.path, "/some/where")

        # complete test dumo to json
        j1 = MessageToJson(e)
        j2 = MessageToJson(e2)
        self.assertEqual(j1, j2)

    def test_header(self):
        e = newEvent("fred", "7734", value=100, message="Hello")
        (hbuf, ebuf) = makeMessage(e, "tiger")

        hdr = EventHeader.FromString(hbuf)

        self.assertEqual(hdr.category, "tiger")
        self.assertEqual(hdr.eid, e.eid)
        self.assertEqual(hdr.tsnano, int(e.tstamp * 1e9))
        self.assertEqual(hdr.msglen, len(ebuf))
