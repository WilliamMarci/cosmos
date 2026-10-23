"""Bounded background image preparation; text layout never waits for decoding."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image
from cosmos_tui.features.reader.cache import ByteCache, image_bytes

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cosmos-inline")


class InlineAssets:
    def __init__(self, documents):
        self.documents = documents
        self.cache = ByteCache(16 * 1024**2, image_bytes)
        self.pending, self.errors = {}, OrderedDict()
        self.lock = RLock()
        self.epoch = self.revision = 0

    def clear(self):
        with self.lock:
            self.epoch += 1
            self.revision += 1
            futures = list(self.pending.values())
            self.pending.clear()
            self.cache.clear()
            self.errors.clear()
            for future in futures:
                future.cancel()

    def request(self, path, resource, bounds):
        doc = self.documents
        identity = doc.media.identity(path)
        if Path(path).suffix.lower() != ".epub":
            local = (
                Path(resource[0]).parent / unquote(urlsplit(resource[1]).path)
            ).resolve()
            identity += doc.media.identity(local)
        key = identity + tuple(resource) + (tuple(bounds), doc.media.image_max_mb)
        with self.lock:
            image = self.cache.get(key)
            if image is not None:
                return image, None
            if key in self.errors:
                self.errors.move_to_end(key)
                return None, self.errors[key]
            if key not in self.pending and len(self.pending) < 4:
                epoch = self.epoch
                future = _POOL.submit(self._prepare, path, resource, bounds)
                self.pending[key] = future
                future.add_done_callback(lambda task: self._complete(key, epoch, task))
        return None, None

    def _prepare(self, path, resource, bounds):
        image = self.documents.asset(path, *resource)
        image.thumbnail(bounds, Image.Resampling.LANCZOS)
        return image

    def _complete(self, key, epoch, future):
        with self.lock:
            if epoch != self.epoch:
                return
            self.pending.pop(key, None)
            try:
                image = future.result()
            except Exception as error:
                self.errors[key] = str(error)
                while len(self.errors) > 64:
                    self.errors.popitem(last=False)
            else:
                self.cache[key] = image
            self.revision += 1
