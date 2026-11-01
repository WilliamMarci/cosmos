"""One output owner: graphics are part of Textual CompositorUpdate batches.
Pinned to Textual 8.2.8 because _display / CompositorUpdate are private APIs.
No sys.stdout, tty writes, alternate-screen management or second render loop here.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import subprocess

from rich.style import Style
from rich.text import Span
from textual._compositor import CompositorUpdate


PLACEHOLDER = "\U0010eeee"
MAX_CHILD_PENDING = 32 * 1024 * 1024


def _truecolor_key(color):
    if color is None:
        return None
    try:
        triplet = color.get_truecolor()
    except Exception:
        return None
    return f"#{triplet.red:02x}{triplet.green:02x}{triplet.blue:02x}"


def _id_color(image_id):
    return f"#{image_id >> 16 & 0xff:02x}{image_id >> 8 & 0xff:02x}{image_id & 0xff:02x}"


def _parse_kitty(sequence):
    if not sequence.startswith("\x1b_G") or not sequence.endswith("\x1b\\"):
        return None
    body = sequence[3:-2]
    header, separator, payload = body.partition(";")
    items = []
    for item in header.split(",") if header else []:
        key, equals, value = item.partition("=")
        if key:
            items.append((key, value if equals else None))
    return items, payload, bool(separator)


def _header(items):
    return ",".join(
        key if value is None else f"{key}={value}" for key, value in items
    )


def _parameter(items, key):
    for item_key, value in items:
        if item_key == key:
            return value
    return None


def _replace(items, key, value):
    replaced = False
    result = []
    for item_key, item_value in items:
        if item_key == key:
            result.append((key, value))
            replaced = True
        else:
            result.append((item_key, item_value))
    if not replaced:
        result.append((key, value))
    return result


class Batch(CompositorUpdate):
    def __init__(self, inner=None, suffix=""):
        self.inner, self.suffix = inner, suffix

    def render_segments(self, console):
        return (self.inner.render_segments(console) if self.inner else "") + self.suffix


class Graphics:
    def __init__(self):
        mode = os.getenv("COSMOS_GRAPHICS", "")
        term = os.getenv("TERM", "").lower()
        self.enabled = mode == "kitty" or (
            mode != "text" and ("kitty" in term or term == "xterm-ghostty")
        )
        self.images = {}
        self.sources = {}
        self.masks = {}
        self.pending = ""
        self.next = (os.getpid() * 1024) & 0xFFFFFF or 1
        self.outer_tmux = bool(os.environ.get("TMUX"))
        # Per-pane child-application images.  The original IDs are chosen by
        # the child; Cosmos maps them to IDs owned by this outer client.
        self.child_maps = {}
        self.child_colors = {}
        self.child_ids = {}
        self.child_chunks = {}
        if self.outer_tmux:
            self._enable_outer_passthrough()

    def _enable_outer_passthrough(self):
        pane = os.environ.get("TMUX_PANE")
        if not pane:
            return
        try:
            subprocess.run(
                [
                    "tmux",
                    "set-option",
                    "-p",
                    "-q",
                    "-t",
                    pane,
                    "allow-passthrough",
                    "on",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def _allocate(self):
        for _ in range(0xFFFFFF):
            self.next = (self.next + 1) & 0xFFFFFF or 1
            if self.next not in self.child_ids and all(
                image_id != self.next for _, image_id in self.images.values()
            ):
                return self.next
        raise RuntimeError("Kitty image id space exhausted")

    def _wrap(self, sequence):
        if not self.outer_tmux:
            return sequence
        return "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"

    def _queue(self, sequence):
        if len(self.pending) + len(sequence) > MAX_CHILD_PENDING:
            logging.getLogger(__name__).warning("child graphics queue exceeded budget")
            return
        self.pending += self._wrap(sequence)

    def _child_id(self, pane, original):
        mapping = self.child_maps.setdefault(pane, {})
        image_id = mapping.get(original)
        if image_id is not None:
            return image_id
        image_id = self._allocate()
        mapping[original] = image_id
        self.child_ids[image_id] = (pane, original)
        self.child_colors.setdefault(pane, {})[
            _id_color(original)
        ] = _id_color(image_id)
        return image_id

    def _drop_child(self, pane, original):
        mapping = self.child_maps.get(pane, {})
        image_id = mapping.pop(original, None)
        if image_id is None:
            return
        self.child_ids.pop(image_id, None)
        self.child_colors.get(pane, {}).pop(_id_color(original), None)
        if not mapping:
            self.child_maps.pop(pane, None)
        if not self.child_colors.get(pane):
            self.child_colors.pop(pane, None)
        if self.child_chunks.get(pane) == original:
            self.child_chunks.pop(pane, None)

    def _delete_child(self, image_id, *, data=True):
        delete = "I" if data else "i"
        self._queue(f"\x1b_Gq=2,a=d,d={delete},i={image_id}\x1b\\")

    def feed_child(self, pane, sequence):
        """Forward one Kitty APC emitted by a program inside a pane."""
        if not self.enabled:
            return
        try:
            text = sequence.decode("ascii")
        except (AttributeError, UnicodeDecodeError):
            return
        parsed = _parse_kitty(text)
        if parsed is None:
            return
        items, payload, separator = parsed
        action = _parameter(items, "a") or "t"
        if action == "q":
            return
        if action == "d":
            self._delete_action(pane, items, payload, separator)
            return
        image = _parameter(items, "i")
        original = int(image) if image and image.isdigit() and int(image) else None
        continuation = image is None
        if continuation:
            original = self.child_chunks.get(pane)
            if original is None:
                return
            more = _parameter(items, "m")
            if more != "1":
                self.child_chunks.pop(pane, None)
            self._write_child(items, payload, separator)
            return
        if original is None:
            return
        if action in ("t", "T", "f", "a"):
            if action == "T" and _parameter(items, "U") != "1":
                return
            image_id = self._child_id(pane, original)
            items = _replace(items, "i", str(image_id))
            more = _parameter(items, "m")
            if more == "1":
                self.child_chunks[pane] = original
            else:
                self.child_chunks.pop(pane, None)
            self._write_child(items, payload, separator)
            return
        if action == "p":
            if _parameter(items, "U") != "1":
                return
            image_id = self._child_id(pane, original)
            items = _replace(items, "i", str(image_id))
            self._write_child(items, payload, separator)
            return
        if action not in ("c",):
            image_id = self._child_id(pane, original)
            items = _replace(items, "i", str(image_id))
            self._write_child(items, payload, separator)

    def _delete_action(self, pane, items, payload, separator):
        delete = _parameter(items, "d") or "a"
        if delete in ("a", "A"):
            for child_id in list(self.child_ids):
                self._delete_child(child_id, data=delete == "A")
            if delete == "A":
                self.child_maps.clear()
                self.child_colors.clear()
                self.child_ids.clear()
                self.child_chunks.clear()
            return
        image = _parameter(items, "i")
        original = int(image) if image and image.isdigit() and int(image) else None
        if original is None:
            return
        if delete in ("i", "I"):
            image_id = self._child_id(pane, original)
            items = _replace(items, "i", str(image_id))
            self._write_child(items, payload, separator)
            if delete == "I":
                self._drop_child(pane, original)
        elif delete == "P":
            image_id = self._child_id(pane, original)
            items = _replace(items, "i", str(image_id))
            self._write_child(items, payload, separator)

    def _write_child(self, items, payload, separator):
        body = _header(items)
        if separator:
            body += ";" + payload
        self._queue(f"\x1b_G{body}\x1b\\")

    def recolor(self, pane, lines):
        mapping = self.child_colors.get(pane)
        if not mapping:
            return lines
        result = []
        for line in lines:
            copy = line.copy()
            changed = False
            spans = []
            for span in copy.spans:
                style = span.style
                if isinstance(style, str):
                    try:
                        style = Style.parse(style)
                    except Exception:
                        spans.append(span)
                        continue
                if style is None:
                    style = Style()
                if not isinstance(style, Style):
                    spans.append(span)
                    continue
                segment = line.plain[span.start : span.end]
                if PLACEHOLDER not in segment:
                    spans.append(span)
                    continue
                replacement = mapping.get(_truecolor_key(style.color))
                if replacement is None:
                    spans.append(span)
                    continue
                spans.append(
                    Span(span.start, span.end, style + Style(color=replacement))
                )
                changed = True
            if changed:
                copy.spans = spans
                result.append(copy)
            else:
                result.append(line)
        return result

    def clear_children(self):
        for image_id in list(self.child_ids):
            self._delete_child(image_id)
        self.child_maps.clear()
        self.child_colors.clear()
        self.child_ids.clear()
        self.child_chunks.clear()

    def cover(self, key, source, x, y, cell, rectangles, color):
        from PIL import ImageDraw

        cw, ch = cell
        regions = []
        for rect in rectangles:
            left, top = max(0, (rect.x - x) * cw), max(0, (rect.y - y) * ch)
            right, bottom = (
                min(source.width, (rect.x + rect.width - x) * cw),
                min(source.height, (rect.y + rect.height - y) * ch),
            )
            if left < right and top < bottom:
                regions.append((left, top, right - 1, bottom - 1))
        if not regions:
            self.masks.pop(key, None)
            return source
        regions = tuple(regions)
        previous = self.masks.get(key)
        if previous and previous[0] is source and previous[1:3] == (regions, color):
            return previous[3]
        image = source.copy()
        draw = ImageDraw.Draw(image)
        for rect in regions:
            draw.rectangle(rect, fill=color)
        self.masks[key] = source, regions, color, image
        return image

    def commit(self, images):
        wanted = {}
        sources = {}
        for key, image, x, y in images:
            sources[key] = (image, x, y)
            previous = self.sources.get(key)
            if previous and previous[0] is image and previous[1:] == (x, y):
                wanted[key] = self.images[key]
                continue
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            data = stream.getvalue()
            fingerprint = hashlib.sha256(data).digest(), x, y
            old = self.images.get(key)
            if old and old[0] == fingerprint:
                wanted[key] = old
                continue
            if old:
                self._queue(f"\x1b_Ga=d,d=I,i={old[1]},q=2\x1b\\")
            image_id = self._allocate()
            encoded = base64.b64encode(data).decode()
            self.pending += f"\x1b[{y + 1};{x + 1}H"
            for i in range(0, len(encoded), 4096):
                m = int(i + 4096 < len(encoded))
                header = (
                    f"a=T,f=100,i={image_id},q=2,C=1,z=-1,m={m}" if i == 0 else f"m={m}"
                )
                self._queue(f"\x1b_G{header};{encoded[i : i + 4096]}\x1b\\")
            wanted[key] = fingerprint, image_id
        for key, (_, image_id) in self.images.items():
            if key not in wanted:
                self._queue(f"\x1b_Ga=d,d=I,i={image_id},q=2\x1b\\")
        for key in list(self.masks):
            if key not in wanted:
                self.masks.pop(key, None)
        self.images = wanted
        self.sources = sources

    def take(self):
        result = self.pending
        self.pending = ""
        return result


def halfblocks(image, width, height):
    from rich.text import Text

    small = image.resize((max(1, width), max(1, height * 2)))
    lines = []
    for y in range(height):
        text = Text()
        for x in range(width):
            a = small.getpixel((x, y * 2))
            b = small.getpixel((x, y * 2 + 1))
            text.append(
                "▀", style=f"rgb({a[0]},{a[1]},{a[2]}) on rgb({b[0]},{b[1]},{b[2]})"
            )
        lines.append(text)
    return lines
