import logging
import random
import time
import unittest
from eventlog.transport import NetTransport

BUNDLE_SIZE = 5
BUNDLES = 100


# generate some data buffers with varying lengths
def gen_buffers(num, minLen, maxLen):
    buffers = []
    for i in range(num):
        blen = random.randint(minLen, maxLen)
        data = ("0123456"[i]) * blen
        buf = '{s:"' + data + '"}\n'
        buffers.append(buf)
    return buffers


class TransportPerfTest(unittest.TestCase):

    def setUp(self):
        self.buffers = gen_buffers(BUNDLE_SIZE, 80, 160)
        self.log = logging.getLogger("perf_test")
        self.transport = NetTransport.createFromEnv()

    def tearDown(self):
        pass

    def test_send(self):

        self.assertTrue(self.transport is not None,
            "EVENTLOG_HOST and EVENTLOG_PORT required for this test")

        if self.transport is None:
            self.log.error("Network not configured. Can't run test")
            return

        t0 = time.time()
        for i in range(BUNDLES):
            self.transport.send(self.buffers)
        t1 = time.time()
        elapsed = t1 - t0

        print("total time elapsed: %f" % elapsed)
        print("time per message: %f" % (elapsed / (BUNDLE_SIZE * BUNDLES)))

        print("Stats: %s" % str(self.transport.get_stats()))
