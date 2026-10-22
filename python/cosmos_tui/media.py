"""Python bitmap / Poppler adapter for the Textual rendering migration."""

from __future__ import annotations
import io
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = 16_000_000


def tool(*args):
    out = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=15,
        env=dict(os.environ, LC_ALL="C"),
    )
    if out.returncode:
        raise RuntimeError(out.stderr.decode(errors="replace")[:500])
    if len(out.stdout) > 32 * 1024 * 1024:
        raise ValueError("decoder output exceeds 32 MiB")
    return out.stdout


class Media:
    def __init__(self):
        self.cache = {}
        self.views = {}
        self.thumbnails = {}

    def load(self, state):
        path = Path(state["path"])
        stat = path.stat()
        page = max(1, int(state.get("page", 1)))
        query = state.get("query", "")
        key = (str(path), stat.st_size, stat.st_mtime_ns, page, query)
        if key in self.cache:
            return self.cache[key]
        pages = 1
        words = []
        extent = (1, 1)
        if path.suffix.lower() == ".pdf":
            import re

            pages = int(re.search(rb"Pages:\s+(\d+)", tool("pdfinfo", str(path)))[1])
            page = min(page, pages)
            image = Image.open(
                io.BytesIO(
                    tool(
                        "pdftoppm",
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        "-singlefile",
                        "-scale-to",
                        "1800",
                        "-png",
                        str(path),
                    )
                )
            ).convert("RGB")
            root = ET.fromstring(
                tool(
                    "pdftotext",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-bbox",
                    str(path),
                    "-",
                )
            )
            for node in root.iter():
                if node.tag.endswith("}page"):
                    extent = float(node.attrib["width"]), float(node.attrib["height"])
                if node.tag.endswith("}word"):
                    words.append(
                        (
                            node.text or "",
                            [
                                float(node.attrib[n])
                                for n in ["xMin", "yMin", "xMax", "yMax"]
                            ],
                        )
                    )
            if query:
                draw = ImageDraw.Draw(image, "RGBA")
                for word, r in words:
                    if query.casefold() in word.casefold():
                        draw.rectangle(
                            (
                                r[0] / extent[0] * image.width,
                                r[1] / extent[1] * image.height,
                                r[2] / extent[0] * image.width,
                                r[3] / extent[1] * image.height,
                            ),
                            fill=(255, 210, 20, 95),
                        )
        else:
            if stat.st_size > 32 * 1024 * 1024:
                raise ValueError("image input exceeds 32 MiB")
            with Image.open(path) as opened:
                if opened.width * opened.height > 16_000_000:
                    raise ValueError("image exceeds pixel budget")
                rgba = opened.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
        result = image, pages, bool(words)
        if len(self.cache) >= 3:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = result
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

    def thumbnail(self, state, bounds):
        path = Path(state["path"])
        stat = path.stat()
        key = str(path), stat.st_size, stat.st_mtime_ns, state.get("page", 1), bounds
        if key in self.thumbnails:
            return self.thumbnails[key]
        if path.suffix.lower() == ".pdf":
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
                        str(min(320, max(bounds))),
                        "-png",
                        str(path),
                    )
                )
            )
        else:
            if stat.st_size > 32 * 1024 * 1024:
                raise ValueError("image input exceeds 32 MiB")
            opened = Image.open(path)
        with opened:
            if opened.width * opened.height > 16_000_000:
                raise ValueError("image exceeds pixel budget")
            image = opened.convert("RGBA")
            image.thumbnail(bounds, Image.Resampling.LANCZOS)
            result = Image.new("RGB", image.size, "white")
            result.paste(image, mask=image.getchannel("A"))
        if len(self.thumbnails) >= 48:
            self.thumbnails.pop(next(iter(self.thumbnails)))
        self.thumbnails[key] = result
        return result

    def viewport(self, source, state, width, height, background):
        key = (id(source), repr(state), width, height, background)
        if key in self.views:
            return self.views[key][1]
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
        if len(self.views) >= 3:
            self.views.pop(next(iter(self.views)))
        self.views[key] = source, image
        return image
