import six
import socket
import sys
import threading
import time
import unittest
from eventlog.transport import NetTransport, TCPSocketFactory, HEALTHCHECK_INTERVAL_SEC

TEST_PORT = 6543


def errlog(s):
    if six.PY3 and isinstance(s, bytes):
        s = s.decode("UTF8")
    sys.stderr.write(s)
    if s[-1] != '\n':
        sys.stderr.write('\n')
    sys.stderr.flush()


def logBlackHole(controller, host, port):
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, port))
        s.listen(1)
    except Exception as e:
        errlog("Test failed to restart listener: %s, exiting" % str(e))
        if s is not None:
            try:
                s.close()
                s = None
            except:  # noqa: E722
                pass
        return
    errlog("Listener thread started")
    try:
        controller.setSocket(s)
        while controller.isListening():
            conn, addr = s.accept()
            controller.newConnection()
            while controller.isListening():
                data = conn.recv(1024)
                if not data:
                    break
            conn.close()
    except Exception as e:
        errlog("Listener thread stopped with %s" % str(e))
    finally:
        errlog("Listen thread exiting")
        controller.setSocket(None)
        s.close()
        s = None


class Controller(object):

    def __init__(self, host, port):
        self._shouldAccept = True
        self._connCount = 0
        self._host = host
        self._port = port
        self._thread = None
        self._socket = None
        self._lock = threading.RLock()

    def isListening(self):
        with self._lock:
            return self._shouldAccept

    def stopListening(self):
        with self._lock:
            self._shouldAccept = False
        if self._socket:
            try:
                self._socket.close()
            except:     # noqa: E722
                # ignore potential race conditions
                # while shutting down test
                pass
            self._socket = None
        self._thread = None

    def startListening(self):
        with self._lock:
            self._shouldAccept = True
        self._thread = threading.Thread(target=logBlackHole, args=(self, self._host, self._port))
        self._thread.start()

    def setSocket(self, sock):
        self._socket = sock

    def newConnection(self):
        self._connCount += 1

    def connectionCount(self):
        return self._connCount


class FailoverLogTest(unittest.TestCase):

    def setUp(self):
        self._testHost = '127.0.0.1'
        self._testPort = TEST_PORT
        self._maxAttempts = 3

        self._controller = Controller(self._testHost, self._testPort)

        self._controller.startListening()
        # give receiver thread time to start
        time.sleep(0.05)
        factory = TCPSocketFactory(self._testHost, self._testPort)
        self._transport = NetTransport(factory, 1, self._maxAttempts)

    def tearDown(self):
        # not strictly necessary, but when running with tracemalloc,
        # avoids errors about leaking sockets
        self._controller.stopListening()
        self._transport.closePoolConnections()
        for (k, v) in self._transport.stats.get_stats():
            errlog("%s: %f" % (k, float(v)))

    def test_full(self):

        tx = self._transport

        buf = ['{s:"0123456"}\n']
        self.assertTrue(tx.checkStatus(), "transport good")
        self.assertEqual(self._controller.connectionCount(), 0)

        # mini-pool test
        # these should all use same connection from pool
        # so should count as one only socket connection
        tx.send(buf)
        tx.send(buf)
        tx.send(buf)
        time.sleep(0.01)
        self.assertEqual(self._controller.connectionCount(), 1)

        # test close(), then send to re-open
        tx.closePoolConnections()
        tx.send(buf)
        time.sleep(0.01)
        self.assertEqual(self._controller.connectionCount(), 2)

        errlog("Stopping listener to check failure handling, sleep 5 sec")
        # test stopListening
        self._controller.stopListening()
        tx.closePoolConnections()
        try:
            tx.send(buf)
            tx.send(buf)
            send_ok = True
        except Exception:
            send_ok = False
        self.assertFalse(send_ok, "send to close receiver should have failed")

        # give it a chance to shut down
        try:
            # send another one just to confirm
            tx.send(buf)
            send_ok = True
        except:               # noqa: E722
            send_ok = False
        self.assertFalse(send_ok, "expect send to fail when transport stopped")
        self.assertFalse(tx.checkStatus(), "transport stopped")

        errlog("Waiting for about 60 seconds. Should see at least one Retry message")
        time.sleep(61)
        self.assertFalse(tx.checkStatus(), "transport stopped")

        errlog("Starting listener again...")
        self._controller.startListening()

        # wait for it to be detected
        time.sleep(HEALTHCHECK_INTERVAL_SEC + 1)
        self.assertTrue(tx.checkStatus(), "transport good")

        # test send works after re-open
        x = self._controller.connectionCount()
        tx.send(buf)
        time.sleep(0.01)
        self.assertEqual(self._controller.connectionCount(), x + 1)
