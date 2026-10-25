"""Read-only quick-open previews sharing Reader decoders and bounded caches."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image
from rich.text import Text
from cosmos_tui.features.reader.cache import ByteCache, image_bytes
from cosmos_tui.features.reader.documents import (
    FORMATS,
    MAX_BOOK,
    read_member,
    member_path,
)


@dataclass
class Preview:
    image: Image.Image | None = None
    lines: list[Text] = field(default_factory=list)
    error: str = ""
    loading: bool = False


def book_cover(path):
    """EPUB 2 metadata and EPUB 3 cover-image, without parsing every chapter."""
    with zipfile.ZipFile(path) as book:
        if (
            len(book.infolist()) > 10000
            or sum(i.file_size for i in book.infolist()) > MAX_BOOK
        ):
            raise ValueError("Expanded EPUB exceeds Reader limits")
        container = ET.fromstring(read_member(book, "META-INF/container.xml"))
        package = next(
            (
                n.get("full-path")
                for n in container.iter()
                if n.tag.endswith("rootfile")
            ),
            None,
        )
        if not package:
            raise ValueError("EPUB has no package")
        package = member_path("", package)
        root = ET.fromstring(read_member(book, package))
        cover_id = next(
            (
                n.get("content")
                for n in root.iter()
                if n.tag.endswith("meta") and n.get("name") == "cover"
            ),
            None,
        )
        for item in root.iter():
            if item.tag.endswith("item") and (
                "cover-image" in item.get("properties", "").split()
                or (cover_id and item.get("id") == cover_id)
            ):
                href = item.get("href")
                if href:
                    return package, href
    return None


def fit_image(image, bounds):
    scale = min(bounds[0] / image.width, bounds[1] / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS) if image.size != size else image


def preview(path, bounds, *, media, documents, columns=40, rows=30):
    """Return first-page image, EPUB cover or rich text. Never open a UI/process app."""
    bounds = tuple(max(1, min(4000, int(v))) for v in bounds)
    path = Path(path)
    if not path.is_file():
        return Preview(lines=[Text("Special file")])
    suffix = path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".pdf"):
        return Preview(
            image=fit_image(
                media.thumbnail(
                    dict(path=str(path), page=1), bounds, max_edge=max(bounds)
                ),
                bounds,
            )
        )
    if suffix in FORMATS:
        if suffix == ".epub":
            cover = book_cover(path)
            if cover:
                image = documents.asset(path, *cover)
                return Preview(image=fit_image(image, bounds))
        from rich.console import Console

        console = Console(width=max(1, columns))
        result = []
        for row in documents.rows(path):
            if row.image and suffix == ".epub":
                image = documents.asset(path, *row.image)
                return Preview(image=fit_image(image, bounds))
            result.extend(row.text.wrap(console, max(1, columns)))
            if len(result) >= rows:
                break
        return Preview(lines=result[:rows])
    from cosmos_tui.features.files.model import preview as text_preview, display

    content = text_preview(dict(path=str(path), directory=False))
    return Preview(
        lines=[
            Text(display(line.expandtabs(4))) for line in content.splitlines()[:rows]
        ]
    )


class QuickPreview:
    """Non-blocking pane-keyed requests; stale queued work is cancelled."""

    def __init__(self, media, documents):
        self.media, self.documents = media, documents
        self.cache = ByteCache(
            16 * 1024**2,
            lambda p: (image_bytes(p.image) if p.image else 0)
            + sum(len(t.plain) * 4 for t in p.lines)
            + len(p.error) * 4
            + 128,
        )
        self.pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="cosmos-preview"
        )
        self.lock = RLock()
        self.pending, self.latest = {}, {}
        self.revision = 0
        self.closed = False

    def render(self, path, bounds, columns, rows, settings):
        from cosmos_tui.features.reader.opener import preview as quick_open

        self.media.configure(settings.get("viewer_cache_mb", 128))
        self.media.disk.configure(settings.get("viewer_disk_cache_mb", 512))
        result = quick_open(
            path,
            bounds,
            media=self.media,
            documents=self.documents,
            columns=columns,
            rows=rows,
        )
        if result.image is not None:
            budget = max(1, self.cache.limit - 4096)
            cost = image_bytes(result.image)
            if cost > budget:
                scale = (budget / cost) ** 0.5
                result.image.thumbnail(
                    (
                        max(1, int(result.image.width * scale)),
                        max(1, int(result.image.height * scale)),
                    )
                )
        return result

    def request(self, owner, path, bounds, columns, rows, settings):
        identity = self.media.identity(path)
        key = identity + (
            bounds,
            columns,
            rows,
            settings.get("viewer_image_max_mb", 32),
        )
        with self.lock:
            self.cache.resize(
                min(
                    16 * 1024**2,
                    max(1024**2, settings.get("viewer_cache_mb", 128) * 1024**2 // 8),
                )
            )
            self.latest[owner] = key
            cached = self.cache.get(key)
            if cached is not None:
                return cached
            if self.closed:
                return Preview()
            # Keep at most two running jobs plus the most recent request per pane.
            for old, future in list(self.pending.items()):
                if old not in self.latest.values() and future.cancel():
                    self.pending.pop(old, None)
            if key not in self.pending:
                self.media.image_max_mb = settings.get("viewer_image_max_mb", 32)
                future = self.pool.submit(
                    self.render, path, bounds, columns, rows, dict(settings)
                )
                self.pending[key] = future
                future.add_done_callback(lambda task: self.finished(key, task))
            return Preview(loading=True)

    def finished(self, key, task):
        with self.lock:
            self.pending.pop(key, None)
            if task.cancelled() or self.closed:
                return
            try:
                result = task.result()
            except Exception as error:
                result = Preview(error=str(error)[:250])
            if key in self.latest.values():
                self.cache[key] = result
                self.revision += 1

    def release(self, owner):
        with self.lock:
            self.latest.pop(owner, None)

    def close(self):
        with self.lock:
            self.closed = True
            self.latest.clear()
            self.cache.clear()
        self.pool.shutdown(wait=False, cancel_futures=True)
