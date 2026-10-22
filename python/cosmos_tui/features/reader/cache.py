"""Thread-safe byte-bounded LRU caches; eviction releases owned references."""

from collections import OrderedDict
from collections.abc import MutableMapping
from threading import RLock


class ByteCache(MutableMapping):
    def __init__(self, limit, cost):
        self.limit, self.cost = limit, cost
        self.data = OrderedDict()
        self.bytes = 0
        self.lock = RLock()

    def __getitem__(self, key):
        with self.lock:
            value, size = self.data[key]
            self.data.move_to_end(key)
            return value

    def __setitem__(self, key, value):
        size = max(1, self.cost(value))
        with self.lock:
            if key in self.data:
                self.bytes -= self.data.pop(key)[1]
            if size <= self.limit:
                self.data[key] = (value, size)
                self.bytes += size
            while self.bytes > self.limit and self.data:
                self.bytes -= self.data.popitem(last=False)[1][1]

    def __delitem__(self, key):
        with self.lock:
            self.bytes -= self.data.pop(key)[1]

    def __iter__(self):
        with self.lock:
            return iter(list(self.data))

    def __len__(self):
        with self.lock:
            return len(self.data)

    def clear(self):
        with self.lock:
            self.data.clear()
            self.bytes = 0

    def resize(self, limit):
        with self.lock:
            self.limit = limit
            while self.bytes > limit and self.data:
                self.bytes -= self.data.popitem(last=False)[1][1]


def image_bytes(image):
    return image.width * image.height * len(image.getbands())
