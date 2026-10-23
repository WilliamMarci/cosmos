"""Local EPUB/HTML/Markdown documents through the adapted ZhihuViewer parser."""

from dataclasses import dataclass
import io
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile
from markdown_it import MarkdownIt
from PIL import Image
from rich.console import Console
from rich.text import Text
from cosmos_tui.features.reader.richparse.htmlparse import parse_html, table_to_text
from cosmos_tui.features.reader.cache import ByteCache

FORMATS = {".epub", ".md", ".markdown", ".html", ".htm"}
MAX_TEXT = 16 * 1024**2
MAX_BOOK = 128 * 1024**2


def member_path(base, relative):
    name = posixpath.normpath(posixpath.join(base, unquote(relative.split("#", 1)[0])))
    if name.startswith(("../", "/")) or name == "..":
        raise ValueError("EPUB resource leaves the book container")
    return name


def read_member(book, name, limit=MAX_TEXT):
    info = book.getinfo(name)
    if info.file_size > limit:
        raise ValueError("EPUB member exceeds configured size limit")
    return book.read(info)


def chapters(path):
    if path.suffix.lower() != ".epub":
        if path.stat().st_size > MAX_TEXT:
            raise ValueError("Rich-text document exceeds 16 MiB")
        data = path.read_text(encoding="utf-8-sig", errors="replace")
        if path.suffix.lower() in (".md", ".markdown"):
            data = MarkdownIt("commonmark", {"html": True}).enable("table").render(data)
        return [(str(path), data)]
    with zipfile.ZipFile(path) as book:
        if (
            len(book.infolist()) > 10000
            or sum(i.file_size for i in book.infolist()) > MAX_BOOK
        ):
            raise ValueError("Expanded EPUB exceeds 128 MiB or 10000 entries")
        container = ET.fromstring(read_member(book, "META-INF/container.xml"))
        rootfile = next(
            (
                n.get("full-path")
                for n in container.iter()
                if n.tag.endswith("rootfile")
            ),
            None,
        )
        if not rootfile:
            raise ValueError("EPUB container has no package")
        rootfile = member_path("", rootfile)
        package = ET.fromstring(read_member(book, rootfile))
        manifest = {n.get("id"): n for n in package.iter() if n.tag.endswith("}item")}
        order = [
            n.get("idref")
            for n in package.iter()
            if n.tag.endswith("itemref") and n.get("linear") != "no"
        ]
        result = []
        for ident in order:
            item = manifest.get(ident)
            if item is None or item.get("media-type") not in (
                "application/xhtml+xml",
                "text/html",
            ):
                continue
            name = member_path(posixpath.dirname(rootfile), item.get("href", ""))
            result.append(
                (name, read_member(book, name).decode("utf-8-sig", errors="replace"))
            )
        if not result:
            raise ValueError("EPUB has no readable spine chapters (DRM is unsupported)")
        return result


def encoded(text):
    return {
        "text": text.plain,
        "spans": [(s.start, s.end, str(s.style)) for s in text.spans],
        "style": str(text.style or ""),
    }


def decoded(value):
    # Rich requires an empty style string; None survives parsing but crashes
    # when a disk-restored row is rendered through Console.get_style().
    text = Text(value["text"], style=value.get("style") or "")
    for start, end, style in value.get("spans", []):
        text.stylize(style, start, end)
    return text


@dataclass
class Row:
    text: Text
    image: tuple | None = None
    heading: bool = False
    block: int = -1
    table: bool = False


class Documents:
    def __init__(self, media, reader=None):
        self.media = media
        from cosmos_tui.features.reader.inline_assets import InlineAssets

        self.assets = InlineAssets(self)
        from cosmos_tui.features.reader.layout import Reader

        self.image_reader = reader if reader is not None else Reader(media)
        self.cache = ByteCache(
            24 * 1024**2, lambda rows: sum(len(r.text.plain) * 4 + 128 for r in rows)
        )
        self.layouts = ByteCache(
            16 * 1024**2, lambda rows: sum(len(r.text.plain) * 4 + 128 for r in rows)
        )
        self.dimensions = ByteCache(1024**2, lambda _: 128)
        self.epoch = 0
        self.console = Console(width=100, color_system="truecolor")

    def clear(self):
        self.epoch += 1
        self.assets.clear()
        self.cache.clear()
        self.layouts.clear()
        self.dimensions.clear()
        self.image_reader.cache.clear()

    def rows(self, path):
        epoch = self.epoch
        identity = self.media.identity(path)
        key = identity + ("rich-zhihu-v2",)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        saved = self.media.disk.json(key)
        if isinstance(saved, list):
            try:
                rows = [
                    Row(
                        decoded(r["text"]),
                        tuple(r["image"]) if r.get("image") else None,
                        r.get("heading", False),
                        r.get("block", -1),
                        r.get("table", False),
                    )
                    for r in saved
                ]
                if epoch == self.epoch:
                    self.cache[key] = rows
                return rows
            except (KeyError, TypeError, ValueError):
                pass
        generation = self.media.disk.generation()
        rows = []
        for chapter, markup in chapters(Path(path)):
            blocks, _ = parse_html(markup)
            for block in blocks:
                first = len(rows)
                if block.kind == "img":
                    for source in block.urls:
                        rows.append(
                            Row(
                                Text(block.caption or "[Image]", style="dim"),
                                (chapter, source),
                            )
                        )
                elif block.kind == "list":
                    rows.extend(Row(t) for t in block.items)
                elif block.kind == "table":
                    rows.append(Row(table_to_text(block), table=True))
                elif block.text is not None:
                    rows.extend(
                        Row(t, heading=block.kind == "h")
                        for t in block.text.split("\n")
                    )
                for row in rows[first:]:
                    row.block = first
                rows.append(Row(Text("")))
        if len(rows) > 100000:
            raise ValueError("Rich-text document exceeds 100000 block rows")
        if not rows:
            rows = [Row(Text("Empty document", style="dim"))]
        if epoch == self.epoch:
            self.cache[key] = rows
        self.media.disk.save_json(
            key,
            [
                {
                    "text": encoded(r.text),
                    "image": r.image,
                    "heading": r.heading,
                    "block": r.block,
                    "table": r.table,
                }
                for r in rows
            ],
            generation,
        )
        return rows

    def layout(self, path, columns, state=None, cell=(10, 20)):
        from cosmos_tui.features.reader.flow import reflow

        state = state or {}
        key = self.media.identity(path) + (
            columns,
            cell,
            state.get("image_rows", 8),
            state.get("line_space", 1),
            state.get("icon_edge", 64),
            tuple(state.get("collapsed_images", [])),
            "wrapped-v2",
        )
        cached = self.layouts.get(key)
        if cached is not None:
            return cached
        epoch = self.epoch
        rows = reflow(self, path, columns, state, cell)
        if epoch == self.epoch:
            self.layouts[key] = rows
        return rows

    def asset_size(self, path, chapter, source):
        """Read image headers for reflow without decoding every book image."""
        parsed = urlsplit(source)
        if parsed.scheme or parsed.netloc:
            raise ValueError("External image is not fetched")
        key = self.media.identity(path) + (chapter, source, "size")
        if Path(path).suffix.lower() != ".epub":
            local = (Path(chapter).parent / unquote(parsed.path)).resolve()
            if not local.is_relative_to(Path(path).resolve().parent):
                raise ValueError("Image outside document directory")
            stamp = self.media.identity(local)
            self.media.check_image_size(local, stamp[1])
            key += stamp
        cached = self.dimensions.get(key)
        if cached is not None:
            return cached
        if Path(path).suffix.lower() == ".epub":
            name = member_path(posixpath.dirname(chapter), source)
            with zipfile.ZipFile(path) as archive:
                with archive.open(name) as stream:
                    if (
                        archive.getinfo(name).file_size
                        > self.media.image_max_mb * 1024**2
                    ):
                        raise ValueError("Book image exceeds configured size limit")
                    with Image.open(stream) as image:
                        size = image.size
        else:
            with Image.open(local) as image:
                size = image.size
        self.dimensions[key] = size
        return size

    def asset(self, path, chapter, source):
        parsed = urlsplit(source)
        if parsed.scheme or parsed.netloc:
            raise ValueError("External image is not fetched")
        identity = self.media.identity(path)
        epoch = self.media.epoch
        if Path(path).suffix.lower() == ".epub":
            name = member_path(posixpath.dirname(chapter), source)
            with zipfile.ZipFile(path) as archive:
                size = archive.getinfo(name).file_size
            if size > self.media.image_max_mb * 1024**2:
                raise ValueError(
                    f"Book image exceeds {self.media.image_max_mb} MiB limit"
                )
            resource = identity + (name,)
            stream = None
        else:
            base = Path(path).resolve().parent
            local = (Path(chapter).parent / unquote(parsed.path)).resolve()
            if not local.is_relative_to(base):
                raise ValueError("Image outside document directory")
            stamp = self.media.identity(local)
            self.media.check_image_size(local, stamp[1])
            resource = identity + stamp
            stream = local
        key = resource + ("rich-asset-v1",)
        cached = self.media.cache.get(key)
        if cached is not None:
            return cached[0].copy()
        generation = self.media.disk.generation()
        image = self.media.disk.image(key)
        if image is None:
            if stream is None:
                with zipfile.ZipFile(path) as archive:
                    data = read_member(archive, name, self.media.image_max_mb * 1024**2)
                if len(data) > self.media.image_max_mb * 1024**2:
                    raise ValueError(
                        f"Book image exceeds {self.media.image_max_mb} MiB limit"
                    )
                stream = io.BytesIO(data)
            with Image.open(stream) as opened:
                if opened.width * opened.height > 16_000_000:
                    raise ValueError("Image exceeds pixel budget")
                rgba = opened.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
            self.media.disk.save_image(key, image, generation)
        self.media.store(self.media.cache, key, (image, 1, False), epoch)
        return image.copy()

    def geometry(self, pane, state):
        from cosmos_tui.features.reader.flow import geometry

        sidebar, width, height, count = geometry(pane, state)
        return sidebar, width, height

    def info(self, pane, state):
        from cosmos_tui.features.reader.flow import position

        rows, sidebar, width, height, count, start = position(self, pane, state)
        stride = height * count
        outline = [
            dict(title=r.text.plain, page=i // stride + 1, line=i, depth=0)
            for i, r in enumerate(rows)
            if r.heading
        ]
        return max(1, (len(rows) + stride - 1) // stride), outline

    def search(self, pane, state, query):
        from cosmos_tui.features.reader.flow import position

        rows, _, _, height, count, _ = position(self, pane, state)
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        result = []
        for i, row in enumerate(rows):
            for _ in pattern.finditer(row.text.plain):
                result.append(dict(page=i // (height * count) + 1, line=i))
                if len(result) >= 10000:
                    return result
        return result

    def render(self, pane, state, palette, cell):
        from cosmos_tui.features.reader.flow import render

        return render(self, pane, state, palette, cell)
