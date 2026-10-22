import asyncio
import base64
import fcntl
import json
import struct
import sys
import termios
from pathlib import Path

from cosmos_tui.core.controller import Controller
from cosmos_tui.features.reader.layout import Reader
from cosmos_tui.features.reader.media import Media
from cosmos_tui.features.search.bar import BottomSearch
from cosmos_tui.input import keymap
from cosmos_tui.render.surface import TerminalSurface
from cosmos_tui.ui.help import Help


class ReaderController(Controller):
    def __init__(self, app):
        super().__init__(app)
        self.media = Media()
        self.reader = Reader(self.media)
        self.frames = {}
        self.pages = {}
        self.revisions = {}
        self.drag = None
        self.pixel_cell = None

    def open_pdf_search(self, pane, state):
        app = self.app
        pid = pane.id

        async def search(query, step):
            target = next((p for p in app.panes if p.id == pid and p.viewer), None)
            if not target:
                raise RuntimeError("Source document pane is no longer available")
            current = json.loads(base64.b64decode(target.viewer))
            if Path(current["path"]).suffix.lower() != ".pdf":
                return "No text layer in this image"
            current["query"] = query
            await self.update_viewer(target, current)
            _, _, has_text = await asyncio.to_thread(self.media.load, current)
            if not has_text:
                return "No text layer"
            return "Search applied on this page" if query else "Search cleared"

        app.push_screen(BottomSearch("PDF", search, initial=state.get("query", "")))

    def cell_pixels(self):
        if self.pixel_cell:
            return self.pixel_cell
        try:
            rows, cols, width, height = struct.unpack(
                "HHHH",
                fcntl.ioctl(sys.__stdin__.fileno(), termios.TIOCGWINSZ, b"\0" * 8),
            )
            if rows and cols and width and height:
                return max(1, round(width / cols)), max(1, round(height / rows))
        except (OSError, ValueError, AttributeError):
            pass
        return 8, 16

    def view_scale(self, pane, state, frame):
        cw, ch = self.cell_pixels()
        sw, sh = frame.source_size
        return max(
            0.001,
            min(frame.main_cols * cw / sw, frame.main_rows * ch / sh)
            * state.get("zoom", 1),
        )

    async def update_viewer(self, pane, state):
        app = self.app
        frame = self.frames.get(pane.id)
        if frame:
            # Clamp in source pixels after every input, not just while rasterizing.
            cw, ch = self.cell_pixels()
            sw, sh = frame.source_size
            scale = min(
                frame.main_cols * cw / sw, frame.main_rows * ch / sh
            ) * state.get("zoom", 1)
            limits = (
                max(0, (sw - frame.main_cols * cw / scale) / 2),
                max(0, (sh - frame.main_rows * ch / scale) / 2),
            )
            state["pan"] = [
                max(-limit, min(limit, value))
                for value, limit in zip(state.get("pan", [0, 0]), limits)
            ]
        wire = base64.b64encode(json.dumps(state).encode()).decode()
        self.revisions[pane.id] = self.revisions.get(pane.id, 0) + 1
        await app.backend.request(f"set-option -p -t {pane.id} @cosmos_viewer {wire}")
        pane.viewer = wire

    def viewer_at(self, event):
        app = self.app
        if app.screen is not app._workspace_screen:
            return None
        return next(
            (
                p
                for p in app.panes
                if p.viewer
                and p.x <= event.screen_x < p.x + p.width
                and p.y <= event.screen_y < p.y + p.height
            ),
            None,
        )

    async def on_mouse_down(self, event):
        app = self.app
        pane = self.viewer_at(event)
        if not pane or event.button != 1:
            return
        frame = self.frames.get(pane.id)
        if not frame:
            return
        event.stop()
        state = json.loads(base64.b64decode(pane.viewer))
        x, y = event.screen_x - pane.x, event.screen_y - pane.y
        for left, top, width, height, index in frame.hits:
            if left <= x < left + width and top <= y < top + height:
                if index < 0:
                    state["thumbnails"] = not state.get("thumbnails", True)
                else:
                    state = self.reader.change(state, index, frame.entries)
                await self.update_viewer(pane, state)
                return
        if y < frame.main_rows and x >= frame.main_x:
            self.drag = pane.id, event.screen_x, event.screen_y
            app.query_one(TerminalSurface).capture_mouse()

    async def on_mouse_move(self, event):
        app = self.app
        if not self.drag:
            return
        pid, x, y = self.drag
        pane = next((p for p in app.panes if p.id == pid and p.viewer), None)
        if pane:
            frame = self.frames.get(pid)
            state = json.loads(base64.b64decode(pane.viewer))
            cw, ch = self.cell_pixels()
            state["pan"] = [
                state["pan"][0]
                - (event.screen_x - x) * cw / self.view_scale(pane, state, frame),
                state["pan"][1]
                - (event.screen_y - y) * ch / self.view_scale(pane, state, frame),
            ]
            self.drag = pid, event.screen_x, event.screen_y
            await self.update_viewer(pane, state)
            event.stop()

    def on_mouse_up(self, event):
        app = self.app
        if self.drag:
            self.drag = None
            app.query_one(TerminalSurface).release_mouse()
            event.stop()

    async def scroll_viewer(self, event, direction):
        pane = self.viewer_at(event)
        if not pane:
            return
        frame = self.frames.get(pane.id)
        if not frame:
            return
        state = json.loads(base64.b64decode(pane.viewer))
        if not event.ctrl and len(frame.entries) > 1:
            state = self.reader.change(state, frame.selected + direction, frame.entries)
        else:
            old_scale = self.view_scale(pane, state, frame)
            state["zoom"] = min(
                8, max(0.25, state["zoom"] * (1.25 if direction < 0 else 1 / 1.25))
            )
            new_scale = (
                old_scale
                * state["zoom"]
                / json.loads(base64.b64decode(pane.viewer))["zoom"]
            )
            cw, ch = self.cell_pixels()
            dx, dy = (
                (event.screen_x - pane.x - frame.main_x + 0.5 - frame.main_cols / 2)
                * cw,
                (event.screen_y - pane.y + 0.5 - frame.main_rows / 2) * ch,
            )
            state["pan"] = [
                state["pan"][0] + dx * (1 / old_scale - 1 / new_scale),
                state["pan"][1] + dy * (1 / old_scale - 1 / new_scale),
            ]
        await self.update_viewer(pane, state)
        event.stop()

    async def on_key(self, event, pane):
        app = self.app
        state = json.loads(base64.b64decode(pane.viewer))
        if event.key in ("q", "escape"):
            self.revisions[pane.id] = self.revisions.get(pane.id, 0) + 1
            self.frames.pop(pane.id, None)
            pane.viewer = ""
            await app.backend.request(f"set-option -pu -t {pane.id} @cosmos_viewer")
            return
        elif event.character == "?":
            app.push_screen(Help("Viewer", keymap.help_rows("viewer", app.settings)))
            return
        elif event.character == "/":
            self.open_pdf_search(pane, state)
            return
        elif event.character in ("+", "=", "-"):
            state["zoom"] = min(
                8,
                max(
                    0.25,
                    state["zoom"] * (1 / 1.25 if event.character == "-" else 1.25),
                ),
            )
        elif event.character == "t":
            state["thumbnails"] = not state.get("thumbnails", True)
        elif event.character == "0":
            state["zoom"] = 1
            state["pan"] = [0, 0]
        elif event.character in ("[", "]"):
            frame = self.frames.get(pane.id)
            if frame:
                state = self.reader.change(
                    state,
                    frame.selected + (1 if event.character == "]" else -1),
                    frame.entries,
                )
        elif event.key in ("up", "down", "left", "right"):
            frame = self.frames.get(pane.id)
            if frame:
                i = 0 if event.key in ("left", "right") else 1
                cw, ch = self.cell_pixels()
                state["pan"][i] += (
                    4 * (cw if i == 0 else ch) / self.view_scale(pane, state, frame)
                ) * (1 if event.key in ("right", "down") else -1)
        await self.update_viewer(pane, state)

    async def prepare(self, pane):
        app = self.app
        state = json.loads(base64.b64decode(pane.viewer))
        revision = self.revisions.get(pane.id, 0)
        source, pages, has_text = await asyncio.to_thread(self.media.load, state)
        frame = await asyncio.to_thread(
            self.reader.render,
            source,
            state,
            pages,
            pane.width,
            pane.height,
            self.cell_pixels(),
            app.role_colors,
            app.graphics.enabled,
        )
        if revision != self.revisions.get(pane.id, 0):
            return
        self.frames[pane.id] = frame
        self.pages[pane.id] = pages
        if pane.active:
            app.message = ""
        if pane.active and not has_text and str(state["path"]).lower().endswith(".pdf"):
            app.message = "No text layer; OCR is not enabled"
        return frame
