"""Non-blocking reading frames and bounded grey loading/error surfaces."""

import asyncio
import base64
import json
import logging
import time
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw
from rich.text import Text
from cosmos_tui.features.reader.layout import ReadingFrame
from cosmos_tui.render.graphics import halfblocks

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class LoadingFrames:
    def __init__(self, controller):
        self.controller = controller
        self.pending, self.ready, self.errors, self.placeholders = {}, {}, {}, {}
        self.probed, self.error_versions = {}, {}
        self.missing = {}

    def key(self, pane):
        app = self.controller.app
        return (
            pane.viewer,
            app.settings.get("viewer_image_max_mb", 32),
            app.settings.get("viewer_pdf_edge", 2400),
            app.settings.get("viewer_pdf_page_mb", 32),
            pane.width,
            pane.height,
            self.controller.cell_pixels(),
            tuple(app.role_colors.items()),
            app.graphics.enabled,
            self.controller.revisions.get(pane.id, 0),
        )

    def frame(self, pane):
        key = self.key(pane)
        ready = self.ready.get(pane.id)
        error = self.errors.get(pane.id)
        elapsed = time.monotonic() - self.probed.get(pane.id, 0)
        if (
            ready
            and not (error and error[0] == key)
            and ready[:2] == (key, self.controller.media.revision)
            and elapsed < 0.5
        ):
            return ready[2]
        if pane.id not in self.pending and not (
            error and error[0] == key and elapsed < 1
        ):
            self.probed[pane.id] = time.monotonic()
            self.pending[pane.id] = asyncio.create_task(self.load(pane, key))
        # Retain an already rendered same-state page while thumbnails fill.
        if (
            ready
            and not (error and error[0] == key)
            and (ready[0] == key or self.missing.get(pane.id) != key)
        ):
            return ready[2]
        return self.placeholder(pane, error[1] if error and error[0] == key else None)

    async def load(self, pane, key):
        identity = None
        session_id = getattr(self.controller.app.backend, "session_id", None)
        try:
            previous = self.errors.get(pane.id)
            if previous and previous[0] == key:
                path = json.loads(base64.b64decode(pane.viewer))["path"]
                identity = await asyncio.to_thread(self.controller.media.identity, path)
                if identity == self.error_versions.get(pane.id):
                    return
            frame = await self.controller.prepare(pane)
            if frame is not None:
                self.ready[pane.id] = key, self.controller.media.revision, frame
                self.errors.pop(pane.id, None)
                self.missing.pop(pane.id, None)
        except Exception as error:
            if self.key(pane) != key:
                return
            detail = str(error)
            try:
                path = json.loads(base64.b64decode(pane.viewer))["path"]
                identity = await asyncio.to_thread(self.controller.media.identity, path)
                if "MiB" not in detail:
                    detail += f" ({identity[1] / 1024**2:.1f} MiB)"
            except (OSError, ValueError, KeyError):
                pass
            previous = self.errors.get(pane.id)
            self.errors[pane.id] = key, detail
            self.error_versions[pane.id] = identity
            self.missing[pane.id] = key
            state = json.loads(base64.b64decode(pane.viewer))
            try:
                entries, selected = await asyncio.to_thread(
                    self.controller.reader.collection,
                    state,
                    self.controller.pages.get(pane.id, 1),
                )
                frame = self.placeholder(pane, detail)
                frame.entries, frame.selected = entries, selected
                frame.hits = []
                self.controller.frames[pane.id] = frame
            except (OSError, ValueError):
                pass
            if previous != (key, detail):
                logging.getLogger(__name__).exception(
                    "Reader render failed for pane %s", pane.id
                )
                await self.controller.app.action_error(
                    "reader", error, session_id=session_id
                )
        finally:
            if self.pending.get(pane.id) is asyncio.current_task():
                self.pending.pop(pane.id, None)

    def placeholder(self, pane, error=None):
        app = self.controller.app
        palette = app.role_colors
        width, height = max(1, pane.width), max(1, pane.height)
        cw, ch = self.controller.cell_pixels()
        try:
            state = json.loads(base64.b64decode(pane.viewer))
        except (ValueError, KeyError):
            state = {"path": "document.pdf"}
        previous = self.ready.get(pane.id)
        previous = previous[2] if previous else None
        document = Path(state["path"]).suffix.lower() == ".pdf"
        expanded = state.get("thumbnails", True) and height >= 12 and width >= 30
        sidebar = (
            (
                min(30, width // 3)
                if state.get("navigation") == "outline"
                else min(18, width // 5)
            )
            if document and expanded
            else 0
        )
        footer = 6 if expanded and not document else 1 if height >= 3 else 0
        main_rows, main_cols = max(1, height - footer), max(1, width - sidebar)
        source_size = (
            previous.source_size
            if previous
            else ((1391, 1800) if document else (800, 600))
        )
        shape = (self.key(pane), error, id(previous))
        cached = self.placeholders.get(pane.id)
        if not cached or cached[0] != shape:
            canvas = (
                previous.image.copy()
                if previous and previous.image.size == (width * cw, height * ch)
                else Image.new("RGB", (width * cw, height * ch), palette["base"])
            )
            draw = ImageDraw.Draw(canvas)
            draw.rectangle(
                (sidebar * cw, 0, width * cw - 1, main_rows * ch - 1),
                fill=palette["bg"],
            )
            sw, sh = source_size
            scale = max(
                0.001,
                min(main_cols * cw / sw, main_rows * ch / sh) * state.get("zoom", 1),
            )
            pan = state.get("pan", [0, 0])
            left = sidebar * cw + (main_cols * cw - sw * scale) / 2 - pan[0] * scale
            top = (main_rows * ch - sh * scale) / 2 - pan[1] * scale
            box = (
                max(sidebar * cw, int(left)),
                max(0, int(top)),
                min(width * cw - 1, int(left + sw * scale) - 1),
                min(main_rows * ch - 1, int(top + sh * scale) - 1),
            )
            draw.rectangle(box, fill=palette["base"], outline=palette["mute"], width=1)
            lines = (
                [line.copy() for line in previous.lines]
                if previous and len(previous.lines) == height
                else [
                    Text(" " * width, style=f"on {palette['base']}")
                    for _ in range(height)
                ]
            )
            for row in range(main_rows):
                lines[row] = lines[row][:sidebar] + Text(
                    " " * main_cols, style=f"on {palette['bg']}"
                )
            if not app.graphics.enabled:
                pixels = halfblocks(canvas, width, height)
                for row in range(main_rows):
                    lines[row] = lines[row][:sidebar] + pixels[row][sidebar:]
            cached = shape, canvas, lines, box, scale
            self.placeholders[pane.id] = cached
        _, canvas, base_lines, box, scale = cached
        lines = [line.copy() for line in base_lines]
        waiting = (
            "Cannot load: " + error
            if error
            else SPINNER[int(time.monotonic() * 10) % len(SPINNER)] + " Loading"
        )
        left_col = max(sidebar, (box[0] + cw - 1) // cw)
        right_col = max(left_col + 1, min(width, box[2] // cw))
        bottom_row = max(0, min(main_rows - 1, box[3] // ch - 1))
        labels = textwrap.wrap(waiting, max(1, right_col - left_col - 1))[-3:]
        for offset, value in enumerate(labels):
            y = max(0, bottom_row - len(labels) + offset + 1)
            label = Text(value, style=f"{palette['mute']} on {palette['base']}")
            x = max(left_col, right_col - label.cell_len)
            lines[y] = lines[y][:x] + label + lines[y][x + label.cell_len :]
        return ReadingFrame(
            canvas,
            lines,
            previous.entries if previous else range(1),
            previous.selected if previous else 0,
            previous.hits if previous else [],
            main_rows,
            sidebar,
            main_cols,
            scale,
            source_size,
            (0, 0),
        )

    def prune(self, visible):
        for store in (
            self.ready,
            self.errors,
            self.placeholders,
            self.probed,
            self.error_versions,
            self.missing,
        ):
            for pid in list(store):
                if pid not in visible:
                    store.pop(pid, None)
        for pid in list(self.pending):
            if pid not in visible:
                self.pending.pop(pid).cancel()

    def clear(self):
        self.prune(set())

    async def close(self):
        tasks = list(self.pending.values())
        self.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
