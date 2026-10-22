"""Non-blocking reading frames and bounded grey loading/error surfaces."""

import asyncio
import base64
import json
import time
from pathlib import Path
from PIL import Image
from rich.text import Text
from cosmos_tui.features.reader.layout import ReadingFrame

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class LoadingFrames:
    def __init__(self, controller):
        self.controller = controller
        self.pending, self.ready, self.errors, self.placeholders = {}, {}, {}, {}
        self.probed, self.error_versions = {}, {}

    def key(self, pane):
        app = self.controller.app
        return (
            pane.viewer,
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
        elapsed = time.monotonic() - self.probed.get(pane.id, 0)
        if (
            ready
            and ready[:2] == (key, self.controller.media.revision)
            and elapsed < 0.5
        ):
            return ready[2]
        error = self.errors.get(pane.id)
        if pane.id not in self.pending and not (
            error and error[0] == key and elapsed < 1
        ):
            self.probed[pane.id] = time.monotonic()
            self.pending[pane.id] = asyncio.create_task(self.load(pane, key))
        # Retain an already rendered same-state page while thumbnails fill.
        if ready and ready[0] == key:
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
        except Exception as error:
            previous = self.errors.get(pane.id)
            self.errors[pane.id] = key, str(error)
            self.error_versions[pane.id] = identity
            if previous != (key, str(error)):
                await self.controller.app.action_error(
                    "reader", error, session_id=session_id
                )
        finally:
            self.pending.pop(pane.id, None)

    def placeholder(self, pane, error=None):
        app = self.controller.app
        palette = app.role_colors
        width, height = max(1, pane.width), max(1, pane.height)
        cw, ch = self.controller.cell_pixels()
        shape = width, height, cw, ch, palette["base"]
        cached = self.placeholders.get(pane.id)
        if not cached or cached[0] != shape:
            cached = shape, Image.new("RGB", (width * cw, height * ch), palette["base"])
            self.placeholders[pane.id] = cached
        style = f"{palette['mute']} on {palette['base']}"
        lines = [
            Text("│" + " " * max(0, width - 2) + "│", style=style)
            for _ in range(height)
        ]
        if width >= 2:
            lines[0] = Text("╭" + "─" * (width - 2) + "╮", style=style)
            if height > 1:
                lines[-1] = Text("╰" + "─" * (width - 2) + "╯", style=style)
        try:
            name = Path(json.loads(base64.b64decode(pane.viewer))["path"]).name
        except (ValueError, KeyError):
            name = "document"
        text = ("Unable to load: " + error) if error else "Loading " + name
        if height > 3 and width > 4:
            label = Text(" " + text, style=style)
            label.truncate(width - 2, overflow="ellipsis")
            lines[height // 2] = Text("│", style=style) + label
            lines[height // 2].pad_right(
                max(0, width - 1 - lines[height // 2].cell_len)
            )
            lines[height // 2].append("│", style=style)
            waiting = (
                "Load failed"
                if error
                else SPINNER[int(time.monotonic() * 10) % len(SPINNER)] + " Loading"
            )
            waiting = Text(waiting, style=f"{palette['mute']} on {palette['base']}")
            waiting.truncate(width - 2)
            lines[-2] = (
                Text("│" + " " * max(0, width - waiting.cell_len - 2), style=style)
                + waiting
                + Text("│", style=style)
            )
        return ReadingFrame(
            cached[1],
            lines,
            range(1),
            0,
            [],
            height,
            0,
            width,
            1,
            cached[1].size,
            (0, 0),
        )

    def prune(self, visible):
        for store in (
            self.ready,
            self.errors,
            self.placeholders,
            self.probed,
            self.error_versions,
        ):
            for pid in list(store):
                if pid not in visible:
                    store.pop(pid, None)
        for pid in list(self.pending):
            if pid not in visible:
                self.pending[pid].cancel()

    def clear(self):
        self.prune(set())

    async def close(self):
        tasks = list(self.pending.values())
        self.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
