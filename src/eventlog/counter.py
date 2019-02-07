import time
import itertools
import platform
import threading


# atomic counter for event id
# Generate unique incrementing ids in a thread-safe way
# For CPython, GIL makes this thread-safe
# In CPython2.7, this is about 10x faster. In CPython 3.7, more than 20x faster.
class AtomicCounterC(object):
    # The CPython GIL may be slightly more efficient
    def __init__(self, initial=0):
        self.value = itertools.count(initial)

    def nextVal(self):
        return next(self.value)


# atomic counter for event id
# Generate unique incrementing ids in a thread-safe way
# For non-CPython, this is safe, but slower than above
class AtomicCounterP(object):

    def __init__(self, initial=0):
        self.value = initial
        self._lock = threading.Lock()

    def nextVal(self):
        with self._lock:
            v = self.value
            self.value += 1
            return v


if platform.python_implementation() == "CPython":
    AtomicCounter = AtomicCounterC
else:
    AtomicCounter = AtomicCounterP


__all__ = [AtomicCounter]


# perf benchmark and threading test for counter class
def testCounter(numThreads, maxval, clz):
    counter = clz()

    def threadCounter():
        for i in range(maxval):
            counter.nextVal()

    threads = []
    for i in range(numThreads):
        thread = threading.Thread(target=threadCounter)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    return (counter.__class__.__name__, counter.nextVal())


# run benchmarks to compare results
def runTests():
    for clz in (AtomicCounterC, AtomicCounterP):
        startT = time.time()
        (kind, val) = testCounter(5, 1000000, clz)
        endT = time.time()
        delta = int((endT - startT) * 1000)
        print("%s: final=%d, time=%d ms" % (kind, val, delta))


if __name__ == '__main__':
    runTests()
