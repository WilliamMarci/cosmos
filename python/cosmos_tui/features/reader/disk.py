"""Byte-bounded, process-safe reader cache; no pickle or executable entries."""

import contextlib
import fcntl
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import tempfile
from PIL import Image


class DiskCache:
    def __init__(self, root=None, megabytes=512):
        self.root = (
            Path(root)
            if root
            else Path(os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache")
            / "cosmos/reader"
        )
        self.limit = int(megabytes) * 1024**2
        self._configured = False

    def path(self, key, suffix):
        digest = hashlib.sha256(
            json.dumps(key, sort_keys=True, default=str).encode()
        ).hexdigest()
        return self.root / (digest + suffix)

    @contextlib.contextmanager
    def locked(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.root / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def generation(self):
        try:
            return (self.root / ".generation").read_text()
        except OSError:
            return ""

    def read(self, key, suffix):
        if not self.limit:
            return None
        path = self.path(key, suffix)
        try:
            with self.locked():
                if path.stat().st_size > min(self.limit, 64 * 1024**2):
                    path.unlink(missing_ok=True)
                    return None
                data = path.read_bytes()
                path.touch()
                return data
        except FileNotFoundError:
            return None
        except OSError as error:
            logging.getLogger(__name__).warning("Reader disk cache read: %s", error)
            return None

    def write(self, key, suffix, data, generation):
        if not self.limit or len(data) > min(self.limit, 64 * 1024**2):
            return
        temp = None
        try:
            with self.locked():
                if generation != self.generation():
                    return
                with tempfile.NamedTemporaryFile(
                    dir=self.root, prefix=".write-", delete=False
                ) as stream:
                    temp = Path(stream.name)
                    stream.write(data)
                os.replace(temp, self.path(key, suffix))
                self.prune_locked()
        except OSError as error:
            logging.getLogger(__name__).warning("Reader disk cache write: %s", error)
        finally:
            if temp:
                temp.unlink(missing_ok=True)

    def prune_locked(self):
        for path in self.root.glob(".write-*"):
            path.unlink(missing_ok=True)
        files = sorted(
            (
                p
                for p in self.root.iterdir()
                if len(p.stem) == 64 and p.suffix in (".png", ".json")
            ),
            key=lambda p: p.stat().st_mtime_ns,
        )
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= self.limit:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size

    def configure(self, megabytes):
        limit = int(megabytes) * 1024**2
        if self.limit == limit and self._configured:
            return
        self._configured = True
        self.limit = limit
        try:
            with self.locked():
                self.prune_locked()
        except OSError:
            pass

    def clear(self):
        import uuid

        with self.locked():
            (self.root / ".generation").write_text(uuid.uuid4().hex)
            for path in self.root.iterdir():
                if len(path.stem) == 64 and path.suffix in (".png", ".json"):
                    path.unlink(missing_ok=True)

    def image(self, key):
        data = self.read(key, ".png")
        if data is not None:
            try:
                with Image.open(io.BytesIO(data)) as image:
                    return image.convert("RGB")
            except (OSError, ValueError, Image.DecompressionBombError):
                try:
                    self.path(key, ".png").unlink(missing_ok=True)
                except OSError:
                    pass
        return None

    def save_image(self, key, image, generation):
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        self.write(key, ".png", stream.getvalue(), generation)

    def json(self, key):
        data = self.read(key, ".json")
        if data is not None:
            try:
                return json.loads(data)
            except (ValueError, UnicodeError):
                try:
                    self.path(key, ".json").unlink(missing_ok=True)
                except OSError:
                    pass
        return None

    def save_json(self, key, value, generation):
        self.write(key, ".json", json.dumps(value).encode(), generation)
