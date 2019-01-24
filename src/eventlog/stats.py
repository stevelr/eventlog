# stat counters for logging handlers

try:
    from prometheus_client import Counter, Gauge
except ImportError:
    # to avoid a forced dependency on prometheus_client,
    # use a super-minimalist implementation of counter.
    # since these are used within same thread, no mutexes are needed.
    class Value:
        def __init__(self, name, desc=''):
            self._name = name
            self._desc = desc
            self._value = 0

        def inc(self, n=1):
            self._value += n

        def dec(self, n=1):
            self._value -= n

        def val(self):
            return (self._name, self._value)

        def reset(self):
            self._value = 0

    class Counter(Value):
        pass

    class Gauge(Value):
        def set(self, n):
            self._value = n


class StatsCollector(object):
    def __init__(self, prefix):
        self._all = []
        self.prefix = prefix

    def get_stats(self):
        return [v.val() for v in self._all]


class LogStats(StatsCollector):

    def __init__(self, prefix):
        super(LogStats, self).__init__(prefix)
        self._events = Counter(prefix + "events_total", "events received")
        self._discarded = Counter(prefix + "discarded_total", "events discarded")
        self._buffered = Gauge(prefix + "buffered_events", "events currently buffered")
        self._sent = Counter(prefix + "sent_total", "events sent to upstream collector")
        self._all.extend([self._events, self._discarded, self._buffered, self._sent])

    def event(self, n=1):
        self._events.inc(n)

    def send(self, n=1):
        self._sent.inc(n)

    def discard(self, n=1):
        self._discarded.inc(n)

    def buffer(self, n=1):
        self._buffered.inc(n)

    def unbuffer(self, n=1):
        self._buffered.dec(min(self._buffered.val()[1], n))


# lookup - finds stat with s in the name. s should be lower case. Used for testing
def lookup(stats, s):
    for (k, v) in stats:
        if k.lower().find(s) != -1:
            return v
