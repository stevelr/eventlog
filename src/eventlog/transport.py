# -*- coding: utf-8 -*-
#
# This software may be modified and distributed under the terms
# of the MIT license.  See the LICENSE file for details.
import logging
import six
import socket
import ssl
import sys
import threading
import time
from collections import deque

from .config import getConfigSetting
from .stats import Counter, StatsCollector
from .handler import ConsoleEventHandler

# package constants
SOCKET_TIMEOUT = int(getConfigSetting(
                    "EVENTLOG_SOCKET_TIMEOUT", 5))

# MAX_SEND_ATTEMPTS is the number of times a message send will be attempted
# before throwing an exception to the caller.
# In development environments, this should be set to 1
MAX_SEND_ATTEMPTS = int(getConfigSetting(
                    "EVENTLOG_MAX_SEND_ATTEMPTS", 3))

# PEAK_CONNECTIONS is size of pool (open connections not in use).
# because connections are used for a very short time window (in testing,
# less than 1ms), the number of connections can be fewer than number of
# worker threads
PEAK_CONNECTIONS = int(getConfigSetting(
                    "EVENTLOG_PEAK_CONNECTIONS", 5))

# MAX_MESSAGE_LEN is length of longest message, above which tx will fail
#
# logproxy receiver supports up to 128k, which is the max length
# of an rsyslog message according to its spec. This number is shorter,
# to catch potential bugs. If the application requires longer messages,
# this could be safely increased to 128 * 1024
MAX_MESSAGE_LEN = int(getConfigSetting(
                    "EVENTLOG_MAX_MESSAGE_LEN", 32 * 1024))

# HEALTH_INTERVAL_SEC is how long we want between checks for log receiver
# This number should be an integer factor of 60: (2,3,4,5,6,10,12,15,20,30)
HEALTHCHECK_INTERVAL_SEC = int(getConfigSetting(
                    "EVENTLOG_HEALTHCHECK_INTERVAL_SEC", 3))
# this number should be a multiple of HEALTHCHECK_INTERVAL_SEC
HEALTHCHECK_PRINT_INTERVAL_SEC = int(getConfigSetting(
                    "EVENTLOG_HEALTHCHECK_PRINT_INTERVAL_SEC", 60))

TRANSPORT_STATS_PREFIX = "eventlog_tx_"


def errlog(s):
    if six.PY3 and isinstance(s, bytes):
        s = s.decode("UTF8")
    sys.stderr.write(s)
    if s[-1] != '\n':
        sys.stderr.write('\n')


# TransportStats holds counters for network messaging
class TransportStats(StatsCollector):
    def __init__(self, prefix):
        super(TransportStats, self).__init__(prefix)
        self._bytes_sent = Counter(prefix + "sent_bytes_total",
                                   "bytes transmitted")
        self._events_sent = Counter(prefix + "sent_msgs_total",
                                    "events transmitted")
        self._socket_errors = Counter(prefix + "socket_errors_total",
                                      "socket disconnects")
        self._time_elapsed = Counter(prefix + "time_elapsed_sec",
                                     "time spent sending, in seconds")
        self._socket_count = Counter(TRANSPORT_STATS_PREFIX + "sockets_created_total",
                            "total number of transport sockets created")
        self._all.extend([self._bytes_sent, self._events_sent,
                         self._socket_errors, self._time_elapsed,
                         self._socket_count])

    def socket_error(self):
        self._socket_errors.inc(1)

    def bytes_sent(self, n):
        self._bytes_sent.inc(n)

    def events_sent(self, n):
        self._events_sent.inc(n)

    def time_elapsed(self, t):
        self._time_elapsed.inc(t)

    def getSocketCounter(self):
        return self._socket_count


# ConnectionPool for maintaining open connections to log server
# This is thread-safe and based on collections.deque.
# If the pool grows past its max length, oldest connections are
# removed first. Note that the pool only holds connections that are not
# in use.
class ConnectionPool:
    def __init__(self, factory, max_size=PEAK_CONNECTIONS):
        self._pool = deque([], maxlen=max_size)
        self._factory = factory

    # take returns a connection, first by checking the pool,
    # and creating one if necessary. take should only return
    # connections that are believed to be "good"
    def take(self):
        try:
            while True:
                c = self._pool.pop()
                if c.isGood():
                    return c
                else:
                    c.close()
        except IndexError:
            # pool empty make another
            return self._makeConnection()

    def release(self, conn):
        if conn is not None:
            if conn.isGood():
                self._pool.append(conn)
            else:
                conn.close()

    def _makeConnection(self):
        return Connection(self._factory.create_socket())

    # Close all connections in the pool
    # Does not close connections that are currently in use
    def closeAll(self):
        while True:
            try:
                self._pool.pop().close()
            except IndexError:
                break


# Connection wraps a socket with a connection status
class Connection(object):

    def __init__(self, sock):
        self._sock = sock
        self._ok = True

    def sendall(self, data):
        if six.PY3 and isinstance(data, str):
            data = bytes(data, 'UTF8')
        self._ok = False
        # if this throws exception, _ok==False will keep it from pool
        self._sock.sendall(data)
        # no errors yet
        self._ok = True

    def isGood(self):
        return self._sock is not None and self._ok

    # reject - signals this connection as bad so it won't be reused
    def reject(self):
        self._ok = False
        self.close()

    # close the socket. (force close - closes even if failures)
    def close(self):
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        finally:
            self._ok = False
            self._sock = None


class BaseTransport(object):
    def __init__(self):
        self.stats = TransportStats(TRANSPORT_STATS_PREFIX)
        self.log = logging.getLogger("eventlog_transport")
        handler = ConsoleEventHandler()
        handler.setLevel(logging.DEBUG)
        self.log.addHandler(handler)
        self.status = True   # assume OK at start
        self.statusLock = threading.RLock()

    def send(self, messages):
        raise Exception("not implemented")

    # Returns True if connection is believed to be available
    def checkStatus(self):
        with self.statusLock:
            return self.status

    def setStatus(self, value):
        with self.statusLock:
            self.status = value

    def get_stats(self):
        return self.stats.get_stats()


class NetTransport(BaseTransport):

    # Construct Tranport with a socket factory and pool size.
    # if poolSize=0, connections aren't pooled and will be recreated each time
    def __init__(self, socketFactory,
                 pool_cap=PEAK_CONNECTIONS,
                 max_attempts=MAX_SEND_ATTEMPTS):
        super(NetTransport, self).__init__()
        self._socketFactory = socketFactory
        self._pool = ConnectionPool(self._socketFactory, pool_cap)
        self._max_attempts = max_attempts

        # pass socket counter hook to Connection class
        self._socketFactory.setCounter(self.stats.getSocketCounter())

    # check confirms that network server is listening by creating
    # one throw-away connection. Uses current conection timeout.
    # If connection is not made, throws exception
    def checkConnection(self):
        self._socketFactory.create_socket(SOCKET_TIMEOUT, False).close()

    # Construct NetTransport using environment variables
    @staticmethod
    def createFromEnv():
        # todo: tls not fully implemented
        host = getConfigSetting('EVENTLOG_HOST')
        port = int(getConfigSetting('EVENTLOG_PORT', 0))
        if host and port:
            factory = TCPSocketFactory(host, port)
            max_attempts = int(getConfigSetting('EVENTLOG_SEND_ATTEMPTS',
                                                MAX_SEND_ATTEMPTS))
            psize = int(getConfigSetting('EVENTLOG_CPOOL_SIZE',
                                                PEAK_CONNECTIONS))
            transport = NetTransport(factory, psize, max_attempts)
            return transport
        return None

    # send - sends a list of messages using transport
    def send(self, messages):
        total_bytes = 0
        total_msgs = 0
        start_time = time.time()
        attemptNum = 0
        exInfo = ""
        # in case we were accidentally called with a single message (byte arr),
        # don't be fooled by len(messages) in following loop
        if not isinstance(messages, list):
            messages = [messages]
        while total_msgs < len(messages) and attemptNum < self._max_attempts:
            # try to send messages, with retries
            # if there is any io error, create a new connection
            # and give load balance a chance to try alternate server
            conn = None
            try:
                conn = self._pool.take()
                for m in messages:
                    conn.sendall(m)
                    total_bytes += len(m)
                    total_msgs += 1
            except Exception as e:
                if conn is not None:
                    conn.reject()  # mark bad so it's not reused
                exInfo = str(e)
                attemptNum += 1
                self.stats.socket_error()
            finally:
                self._pool.release(conn)
            if attemptNum < self._max_attempts:
                time.sleep(0.05)
        self.stats.events_sent(total_msgs)
        self.stats.bytes_sent(total_bytes)
        self.stats.time_elapsed(time.time() - start_time)
        if total_msgs < len(messages):
            # immediately after log receiver goes down, there could be
            # multiple threads that each get to this point and
            # try to launch the checker thread. The waitTillUp() method
            # uses a lock to guarantee only one checker thread is created.
            self.waitTillUp()
            self.closePoolConnections()
            raise Exception("Too many failures trying to send events: %s" % exInfo)

    # close all connections
    # next send operation will open a new connection
    def closePoolConnections(self):
        self._pool.closeAll()

    # The purpose of the checker thread is to keep the server running smoothly
    # if log receiver is down.  If every log attempt tried to contact
    # a failing receiver, this server would slow to a crawl as all
    # worker threads wait for connections and retry logic. As soon as the first
    # log write fails, the status flag is set to false, sending all other
    # logs to the failover log handler immediatly. Meanshile, this thread
    # keeps checkin, and as soon as the log receiver is up, status is set True,
    # and log sending resumes.
    # Once the reciever is up, the checker thread has achieved its purpose and exits.
    def waitTillUp(self):

        # we might get called from multiple threads. Ensure that
        # only one of them starts background thread
        with self.statusLock:
            if not self.checkStatus():
                return
            # status was good but now we need to start thread
            self.setStatus(False)

        # Main loop of background thread to check for log receiver
        # As soon as connection is made, updates status to True and exits.
        def checker(transport):
            tick = 0
            while True:
                err = ""
                try:
                    transport.checkConnection()
                    # it worked! get outta here
                    transport.setStatus(True)
                    break
                except Exception as e:
                    # connection failed
                    err = str(e)
                try:
                    # keep waiting, but log each minute as reminder
                    tick += 1
                    if tick % (HEALTHCHECK_PRINT_INTERVAL_SEC // HEALTHCHECK_INTERVAL_SEC) == 0:
                        errlog("Retry: attempt to connect to %s failed: %s" %
                            (self._socketFactory.info(), err))
                    time.sleep(HEALTHCHECK_INTERVAL_SEC)
                except Exception as e:
                    errlog("checker internal error: %s" % str(e))

        t = threading.Thread(target=checker, args=(self,))
        t.daemon = True
        t.start()


# TCPSocketFactory creates new TCP Sockets, with optional TLS
class TCPSocketFactory():

    def __init__(self, host, port,
                 tls_enable=False, tls_verify=False,
                 keyfile=None, certfile=None, ca_certs=None):
        self._host = host
        self._port = int(port)
        self._tls_enable = tls_enable
        self._tls_verify = tls_verify
        self._keyfile = keyfile
        self._certfile = certfile
        self._ca_certs = ca_certs
        self._counter = None

    def info(self):
        return "TCPSocketFactory(%s:%d)" % (self._host, self._port)

    def setCounter(self, ctr):
        self._counter = ctr

    def create_socket(self, timeout=SOCKET_TIMEOUT, stats=True):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((self._host, self._port))

        # non-SSL
        if not self._tls_enable:
            if stats and self._counter is not None:
                self._counter.inc(1)
            return sock

        # TLS
        cert_reqs = ssl.CERT_REQUIRED
        if not self._tls_verify:
            if self._ca_certs:
                cert_reqs = ssl.CERT_OPTIONAL
            else:
                cert_reqs = ssl.CERT_NONE
        sock = ssl.wrap_socket(
            sock,
            keyfile=self._keyfile,
            certfile=self._certfile,
            ca_certs=self._ca_certs,
            cert_reqs=cert_reqs)
        return sock

    def __repr__(self):
        return "TCPSocketFactory[host=%s, port=%d]" % (self._host, self._port)
