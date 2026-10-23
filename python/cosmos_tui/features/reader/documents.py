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
from cosmos_tui.features.reader.layout import ReadingFrame
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
    text = Text(value["text"], style=value.get("style") or None)
    for start, end, style in value.get("spans", []):
        text.stylize(style, start, end)
    return text


@dataclass
class Row:
    text: Text
    image: tuple | None = None
    heading: bool = False


class Documents:
    def __init__(self, media):
        self.media = media
        self.cache = ByteCache(
            24 * 1024**2, lambda rows: sum(len(r.text.plain) * 4 + 128 for r in rows)
        )
        self.layouts = ByteCache(
            16 * 1024**2, lambda rows: sum(len(r.text.plain) * 4 + 128 for r in rows)
        )
        self.epoch = 0
        self.console = Console(width=100, color_system="truecolor")

    def clear(self):
        self.epoch += 1
        self.cache.clear()
        self.layouts.clear()

    def rows(self, path):
        epoch = self.epoch
        identity = self.media.identity(path)
        key = identity + ("rich-zhihu-v1",)
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
                    rows.extend(Row(t) for t in table_to_text(block).split("\n"))
                elif block.text is not None:
                    rows.extend(
                        Row(t, heading=block.kind == "h")
                        for t in block.text.split("\n")
                    )
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
                {"text": encoded(r.text), "image": r.image, "heading": r.heading}
                for r in rows
            ],
            generation,
        )
        return rows

    def layout(self, path, columns):
        epoch = self.epoch
        identity = self.media.identity(path)
        key = identity + (columns, "wrapped-v1")
        cached = self.layouts.get(key)
        if cached is not None:
            return cached
        result = []
        for row in self.rows(path):
            if row.image:
                result.append(row)
                result.extend(Row(Text("")) for _ in range(7))
            else:
                result.extend(
                    Row(t, heading=row.heading and i == 0)
                    for i, t in enumerate(
                        row.text.wrap(self.console, max(1, columns), overflow="fold")
                    )
                )
            if len(result) > 200000:
                raise ValueError("Reflowed document exceeds 200000 rows")
        if epoch == self.epoch:
            self.layouts[key] = result
        return result

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
        sidebar = (
            min(26, pane.width // 3)
            if state.get("thumbnails", True) and pane.width >= 45 and pane.height >= 12
            else 0
        )
        return sidebar, max(1, pane.width - sidebar - 2), max(1, pane.height - 1)

    def info(self, pane, state):
        _, columns, height = self.geometry(pane, state)
        rows = self.layout(state["path"], columns)
        outline = [
            dict(title=r.text.plain, page=i // height + 1, depth=0)
            for i, r in enumerate(rows)
            if r.heading
        ]
        return max(1, (len(rows) + height - 1) // height), outline

    def search(self, pane, state, query):
        _, columns, height = self.geometry(pane, state)
        rows = self.layout(state["path"], columns)
        # Preserve every match; callers cycle within and across logical pages.
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        result = []
        for i, row in enumerate(rows):
            for _ in pattern.finditer(row.text.plain):
                result.append(dict(page=i // height + 1, line=i))
                if len(result) >= 10000:
                    return result
        return result

    def render(self, pane, state, palette, cell):
        epoch = self.epoch
        sidebar, columns, height = self.geometry(pane, state)
        rows = self.layout(state["path"], columns)
        pages, outline = self.info(pane, state)
        page = min(pages, max(1, int(state.get("page", 1))))
        cw, ch = cell
        canvas = Image.new("RGB", (pane.width * cw, pane.height * ch), palette["bg"])
        lines = [
            Text(" " * pane.width, style=f"{palette['fg']} on {palette['bg']}")
            for _ in range(pane.height)
        ]
        start = (page - 1) * height
        for index in range(max(0, start - 7), min(len(rows), start + height)):
            if epoch != self.epoch:
                break
            row = rows[index]
            y = index - start
            if y < 0 and not row.image:
                continue
            text = row.text.copy()
            if state.get("query"):
                text.highlight_regex(
                    re.escape(state["query"]),
                    f"black on {palette['accl']}",
                    re_flags=re.IGNORECASE,
                )
            text.truncate(columns)
            x = sidebar + 1
            if y >= 0:
                lines[y] = lines[y][:x] + text + lines[y][x + text.cell_len :]
            if row.image:
                try:
                    image = self.asset(state["path"], *row.image)
                    bounds = (columns * cw, 8 * ch)
                    image.thumbnail(bounds, Image.Resampling.LANCZOS)
                    canvas.paste(image, (x * cw, y * ch))
                    # Text stays blank over the image; the image and text share output ownership.
                    if y >= 0:
                        lines[y] = Text(" " * pane.width, style=f"on {palette['bg']}")
                except (
                    OSError,
                    ValueError,
                    Image.DecompressionBombError,
                    zipfile.BadZipFile,
                ) as error:
                    if y < 0:
                        continue
                    label = Text(f"[Image: {error}]", style=palette["mute"])
                    label.truncate(columns)
                    lines[y] = lines[y][:x] + label + lines[y][x + label.cell_len :]
        hits = []
        if sidebar:
            title = Text(
                " Outline ".ljust(sidebar),
                style=f"{palette['accl']} on {palette['base']}",
            )
            lines[0] = title + lines[0][sidebar:]
            offset = max(0, int(state.get("outline_scroll", 0)))
            for y, item in enumerate(outline[offset : offset + height - 1], 1):
                text = Text(
                    " " + item["title"], style=f"{palette['fg']} on {palette['base']}"
                )
                text.truncate(sidebar)
                text.pad_right(max(0, sidebar - text.cell_len))
                lines[y] = text + lines[y][sidebar:]
                hits.append(
                    (0, y, sidebar, 1, ("outline", item["page"], offset + y - 1))
                )
        footer = Text(
            " " + Path(state["path"]).name,
            style=f"{palette['fg']} on {palette['base']}",
        )
        footer.truncate(max(0, pane.width - 14))
        footer.pad_right(max(0, pane.width - 14 - footer.cell_len))
        footer.append(f" {page}/{pages} ".rjust(14))
        footer.truncate(pane.width)
        lines[-1] = footer
        # Character fallback retains readable text and captions, never halfblocks over text.
        frame = ReadingFrame(
            canvas,
            lines,
            range(1, pages + 1),
            page - 1,
            hits,
            height,
            sidebar,
            pane.width - sidebar,
            1,
            canvas.size,
            (0, 0),
        )
        return frame, pages
