"""Python bitmap / Poppler adapter for the Textual rendering migration."""

from __future__ import annotations

import io
import os
import subprocess
import select
import tempfile
import time
from threading import RLock
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw
from cosmos_tui.features.reader.cache import ByteCache, image_bytes
from cosmos_tui.features.reader.pdf import metadata, parse_words, matches
from cosmos_tui.features.reader.disk import DiskCache
from cosmos_tui.features.reader.raster import render_pdf

Image.MAX_IMAGE_PIXELS = 16_000_000


def tool(*args):
    # Bound output while reading, rather than checking after capture_output has
    # already allocated an arbitrarily large XML/raster response.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            env=dict(os.environ, LC_ALL="C"),
        )
        output = bytearray()
        deadline = time.monotonic() + 15
        try:
            while True:
                remaining = deadline - time.monotonic()
                if (
                    remaining <= 0
                    or not select.select([process.stdout], [], [], remaining)[0]
                ):
                    raise RuntimeError("PDF decoder timed out after 15 seconds")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > 64 * 1024 * 1024:
                    raise ValueError("decoder output exceeds 64 MiB")
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if process.returncode:
                errors.seek(0)
                raise RuntimeError(errors.read(500).decode(errors="replace"))
            return bytes(output)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("PDF decoder timed out after 15 seconds") from error
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()


class Media:
    def __init__(self):
        self._lock = RLock()
        self.image_max_mb = 32
        self.disk = DiskCache()
        self.pdf_edge = 2400
        self.pdf_page_mb = 32
        self.resolutions = {}
        self.revision = 0
        self.epoch = 0
        self.versions = OrderedDict()
        self.cache = ByteCache(48 * 1024**2, lambda value: image_bytes(value[0]))
        self.views = ByteCache(
            24 * 1024**2, lambda value: image_bytes(value[1]) + image_bytes(value[0])
        )
        self.thumbnails = ByteCache(12 * 1024**2, image_bytes)
        self.documents = ByteCache(
            12 * 1024**2, lambda value: len(repr(value).encode()) * 2
        )

    def check_image_size(self, path, size):
        if Path(path).suffix.lower() != ".pdf" and size > self.image_max_mb * 1024**2:
            raise ValueError(
                f"Image {size / 1024**2:.1f} MiB exceeds {self.image_max_mb} MiB limit"
            )

    def configure(self, megabytes):
        budget = int(megabytes) * 1024**2
        for cache, share in [
            (self.cache, 0.4),
            (self.views, 0.2),
            (self.thumbnails, 0.1),
            (self.documents, 0.1),
        ]:
            cache.resize(int(budget * share))

    def identity(self, path):
        with self._lock:
            path = Path(path).resolve()
            stat = path.stat()
            key = (str(path), stat.st_size, stat.st_mtime_ns)
            if self.versions.get(str(path)) not in (None, key):
                self.release(str(path))
            self.versions[str(path)] = key
            self.versions.move_to_end(str(path))
            while len(self.versions) > 64:
                self.versions.popitem(last=False)
            return key

    def release(self, path=None):
        with self._lock:
            self.epoch += 1
            for cache in (self.cache, self.views, self.thumbnails, self.documents):
                # Derived views own source references; release them when a document closes.
                if path is None or cache is self.views:
                    cache.clear()
                else:
                    for key in list(cache):
                        if key[0] == str(Path(path).resolve()):
                            cache.pop(key, None)
            if path is None:
                self.versions.clear()
            else:
                self.versions.pop(str(Path(path).resolve()), None)
            self.revision += 1

    def store(self, cache, key, value, epoch, *, changed=False):
        # Compare and insertion share the release lock: a finished old decoder
        # cannot repopulate a cache after the user has cleared it.
        with self._lock:
            if epoch != self.epoch:
                return
            cache[key] = value
            if changed:
                self.revision += 1

    def info(self, path):
        from cosmos_tui.core.features import enabled

        if not enabled("pdf"):
            raise RuntimeError("PDF was not selected during installation")
        key = self.identity(path) + ("metadata",)
        epoch = self.epoch
        result = self.documents.get(key)
        if result is None:
            disk_key = key + ("metadata-v2",)
            result = self.disk.json(disk_key)
            if not (
                isinstance(result, list)
                and len(result) == 2
                and isinstance(result[0], int)
                and isinstance(result[1], list)
            ):
                generation = self.disk.generation()
                result = metadata(str(path))
                self.disk.save_json(disk_key, result, generation)
            self.store(self.documents, key, result, epoch)
        return result

    def text(self, path, page=None):
        key = self.identity(path) + ("text", page)
        epoch = self.epoch
        result = self.documents.get(key)
        if result is None:
            disk_key = key + ("words-v2",)
            result = self.disk.json(disk_key)
            if isinstance(result, list) and all(
                isinstance(p, dict) and "words" in p and "extent" in p for p in result
            ):
                self.store(self.documents, key, result, epoch)
                return result
            generation = self.disk.generation()
            args = ["pdftotext"]
            if page is not None:
                args += ["-f", str(page), "-l", str(page)]
            result = parse_words(tool(*args, "-bbox", str(path), "-"))
            self.disk.save_json(disk_key, result, generation)
            self.store(self.documents, key, result, epoch)
        return result

    def search(self, path, query):
        pages = self.text(path)
        results = []
        for number, page in enumerate(pages, 1):
            for boxes in matches(page, query):
                results.append(dict(page=number, boxes=boxes, extent=page["extent"]))
                if len(results) >= 10000:
                    return results, any(page["words"] for page in pages)
        return results, any(page["words"] for page in pages)

    def load(self, state):
        path = Path(state["path"])
        identity = self.identity(path)
        self.check_image_size(path, identity[1])
        epoch = self.epoch
        pages = self.info(path)[0] if path.suffix.lower() == ".pdf" else 1
        page = min(pages, max(1, int(state.get("page", 1))))
        key = identity + (page,)
        result = self.cache.get(key)
        if result is None:
            disk_key = identity + ("bitmap-v3", page, self.pdf_edge, self.pdf_page_mb)
            generation = self.disk.generation()
            image = self.disk.image(disk_key)
            if path.suffix.lower() == ".pdf":
                if image is None:
                    image, resolution = render_pdf(
                        path, page, tool, self.pdf_edge, self.pdf_page_mb
                    )
                    self.resolutions[key] = resolution
                    self.disk.save_image(disk_key, image, generation)
                try:
                    words = self.text(path, page) if epoch == self.epoch else []
                    has_text = bool(words and words[0]["words"])
                except (OSError, RuntimeError, ValueError):
                    has_text = False
            elif image is None:
                with Image.open(path) as opened:
                    if opened.width * opened.height > 16_000_000:
                        raise ValueError("image exceeds pixel budget")
                    rgba = opened.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "white")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                self.disk.save_image(disk_key, image, generation)
                has_text = False
            else:
                has_text = False
            result = image, pages, has_text
            self.store(self.cache, key, result, epoch, changed=True)
        query = state.get("query", "")
        if query and path.suffix.lower() == ".pdf":
            highlight_key = identity + (
                "highlight",
                page,
                query,
                state.get("active_match"),
            )
            highlighted = self.cache.get(highlight_key)
            if highlighted is None:
                words = self.text(path, page)[0]
                image = result[0].copy()
                draw = ImageDraw.Draw(image, "RGBA")
                for match_index, boxes in enumerate(matches(words, query)):
                    for box in boxes:
                        draw.rectangle(
                            tuple(
                                value
                                / words["extent"][i % 2]
                                * (image.width if i % 2 == 0 else image.height)
                                for i, value in enumerate(box)
                            ),
                            fill=(255, 135, 30, 160)
                            if match_index == state.get("active_match")
                            else (255, 210, 20, 95),
                        )
                highlighted = image, pages, result[2]
                self.store(self.cache, highlight_key, highlighted, epoch)
            return highlighted
        return result

    @staticmethod
    def geometry(source, state, width, height):
        scale = max(
            0.001,
            min(width / source.width, height / source.height)
            * float(state.get("zoom", 1)),
        )
        pan = state.get("pan", [0, 0])
        limits = (
            max(0, (source.width - width / scale) / 2),
            max(0, (source.height - height / scale) / 2),
        )
        return scale, tuple(
            max(-limit, min(limit, value)) for value, limit in zip(pan, limits)
        )

    def thumbnail(self, state, bounds, wait=True, *, max_edge=320):
        path = Path(state["path"])
        identity = self.identity(path)
        self.check_image_size(path, identity[1])
        key = identity + (state.get("page", 1), bounds, max_edge)
        epoch = self.epoch
        cached = self.thumbnails.get(key)
        if cached is not None:
            return cached
        if path.suffix.lower() == ".pdf":
            full = self.cache.get(identity + (int(state.get("page", 1)),))
            if full is not None:
                result = full[0].copy()
                result.thumbnail(bounds, Image.Resampling.LANCZOS)
                self.store(self.thumbnails, key, result, epoch)
                return result
            if not wait:
                for existing in self.thumbnails:
                    if existing[:4] == key[:4]:
                        cached = self.thumbnails.get(existing)
                        if cached is not None:
                            result = cached.copy()
                            result.thumbnail(bounds, Image.Resampling.LANCZOS)
                            self.store(self.thumbnails, key, result, epoch)
                            return result
                return None
            opened = Image.open(
                io.BytesIO(
                    tool(
                        "pdftoppm",
                        "-f",
                        str(state["page"]),
                        "-l",
                        str(state["page"]),
                        "-singlefile",
                        "-scale-to",
                        str(min(max_edge, max(bounds))),
                        "-png",
                        str(path),
                    )
                )
            )
        else:
            opened = Image.open(path)
        with opened:
            if opened.width * opened.height > 16_000_000:
                raise ValueError("image exceeds pixel budget")
            image = opened.convert("RGBA")
            image.thumbnail(bounds, Image.Resampling.LANCZOS)
            result = Image.new("RGB", image.size, "white")
            result.paste(image, mask=image.getchannel("A"))
        self.store(
            self.thumbnails,
            key,
            result,
            epoch,
            changed=path.suffix.lower() == ".pdf",
        )
        return result

    def viewport(self, source, state, width, height, background):
        key = (id(source), repr(state), width, height, background)
        epoch = self.epoch
        cached = self.views.get(key)
        if cached is not None:
            return cached[1]
        width, height = max(1, int(width)), max(1, int(height))
        if width * height > 16_000_000:
            raise ValueError("viewport exceeds 16 million pixels")
        scale, pan = self.geometry(source, state, width, height)
        ox = (width - source.width * scale) / 2 - pan[0] * scale
        oy = (height - source.height * scale) / 2 - pan[1] * scale
        # Transform directly into the bounded viewport; zoom never allocates a giant intermediate.
        image = source.transform(
            (width, height),
            Image.Transform.AFFINE,
            (1 / scale, 0, -ox / scale, 0, 1 / scale, -oy / scale),
            resample=Image.Resampling.BILINEAR,
            fillcolor=background,
        )
        self.store(self.views, key, (source, image), epoch)
        return image
