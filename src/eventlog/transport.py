# -*- coding: utf-8 -*-
#
# This software may be modified and distributed under the terms
# of the MIT license.  See the LICENSE file for details.
import logging
import socket
import ssl
import sys
import time
from collections import deque
from contextlib import contextmanager

from .config import getConfigSetting
from .stats import Counter, StatsCollector
from .handler import ConsoleEventHandler

# package constants
SOCKET_TIMEOUT = 5.0
# MAX_SEND_ATTEMPTS is the number of times a message send will be attempted
# before throwing an exception to the caller.
# In development environments, this should be set to 1
MAX_SEND_ATTEMPTS = 3
# PEAK_CONNECTIONS is size of pool (open connections not in use).
# because connections are used for a very short time window (in testing,
# less than 1ms), the number of connections can be fewer than number of
# worker threads
PEAK_CONNECTIONS = 5

# MAX_MESSAGE_LEN is length of longest message, above which tx will fail
#
# logproxy receiver supports up to 128k, which is the max length
# of an rsyslog message according to its spec. This number is shorter,
# to catch potential bugs. If the application requires longer messages,
# this could be safely increased to 128 * 1024
MAX_MESSAAGE_LEN = 32 * 1024

TRANSPORT_STATS_PREFIX = "eventlog_tx_"


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
        self._all.extend([self._bytes_sent, self._events_sent,
                         self._socket_errors, self._time_elapsed])

    def socket_error(self):
        self._socket_errors.inc(1)

    def bytes_sent(self, n):
        self._bytes_sent.inc(n)

    def events_sent(self, n):
        self._events_sent.inc(n)

    def time_elapsed(self, t):
        self._time_elapsed.inc(t)


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
        except IndexError:
            return self.makeConnection()

    def release(self, conn):
        if conn.isGood():
            self._pool.append(conn)

    def makeConnection(self):
        return self._factory.create_socket()

    # Close all connections in the pool
    # Does not close connections that are currently in use
    def closeAll(self):
        map(lambda c: c.close(), self._pool)
        self._pool.clear()


# Connection wraps a socket with a connection status
class Connection(object):

    def __init__(self, sock):
        self._sock = sock
        self._ok = True

    def sendall(self, data):
        try:
            self._sock.sendall(data)
        except Exception:
            self._ok = False
            raise

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
            self._sock = None


class BaseTransport(object):
    def __init__(self):
        self.stats = TransportStats(TRANSPORT_STATS_PREFIX)
        self.log = logging.getLogger("eventlog_transport")
        self.log.addHandler(ConsoleEventHandler())

    def send(self, messages):
        raise Exception("not implemented")

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
        self._max_atempts = max_attempts

    # check confirms that network server is listening by creating
    # one throw-away connection. Uses current conection timeout.
    # If connection is not made, throws exception
    def check(self):
        nc = self._socketFactory.create_socket()
        nc.close()

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

    # getConnection returns a connection from the pool
    # The contextmanager allows the connection to be used
    # inside python's "with" statement to ensure it is returned to the pool
    # regardless of whether or not an exception occurs while sending
    @contextmanager
    def getConnection(self, attemptNum=0):
        if attemptNum > 0:
            # if we are in a retry loop, always use new connections instead of pool
            # If a server goes down or reboots, this procedure should
            # cause the pool of dead connections to be cleaned out
            # (deque removes from front when appending at its size limit)
            conn = self._socketFactory.create_socket()
        else:
            # Use connection pool
            conn = self._pool.take()
        try:
            yield conn
        finally:
            if conn.isGood():
                self._pool.release(conn)
            else:
                conn.close()

    # send - sends a list of messages using transport
    def send(self, messages):
        total_bytes = 0
        total_msgs = 0
        start_time = time.time()
        attemptNum = 0
        ex = None
        # in case we were accidentally called with a single message (byte arr),
        # don't be fooled by len(messages) in following loop
        if not isinstance(messages, list):
            messages = [messages]
        while total_msgs < len(messages) and attemptNum < self._max_atempts:
            # try to send messages, with retries
            # if there is any io error, create a new connection
            # and give load balance a chance to try alternate server
            with self.getConnection(attemptNum) as conn:
                try:
                    for m in messages:
                        conn.sendall(m)
                        total_bytes += len(m)
                        total_msgs += 1
                except Exception as e:
                    ex = e
                    attemptNum += 1
                    self.stats.socket_error()
                    self.log.error("Send failure #%d/%d: %s" %
                                   (attemptNum, self._max_atempts, str(e)))
        self.stats.events_sent(total_msgs)
        self.stats.bytes_sent(total_bytes)
        self.stats.time_elapsed(time.time() - start_time)
        if total_msgs < len(messages):
            if ex is not None:
                raise ex
            raise Exception("Too many failures trying to send events")


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

    def create_socket(self, timeout=SOCKET_TIMEOUT):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self._host, self._port))
        except Exception as ex:
            sys.stderr.write("ERROR: opening transport to host=%s, port=%d %s\n"
                             % (self._host, self._port, str(ex)))
            raise

        # non-SSL
        if not self._tls_enable:
            return Connection(sock)

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
        return Connection(sock)

    def __repr__(self):
        return "TCPSocketFactory[host=%s, port=%d]" % (self._host, self._port)
