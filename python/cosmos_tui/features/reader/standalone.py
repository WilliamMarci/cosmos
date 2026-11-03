"""Reader-only terminal host; no coordinator, shell or Tmux session."""
import base64
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

from textual.app import App
from textual.widgets import Static

from cosmos_tui.features.reader.controller import ReaderController
from cosmos_tui.features.reader.opener import SUPPORTED
from cosmos_tui.render.graphics import Graphics
from cosmos_tui.render.output import OutputController
from cosmos_tui.render.surface import TerminalSurface
from cosmos_tui.terminal.tmux import Pane
from cosmos_tui.ui.cells import UIRegistry
from cosmos_tui.ui.styles import DARK, WORKSPACE_CSS


class ReaderApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS = WORKSPACE_CSS
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self, path, *, mouse_mode="auto"):
        from cosmos_tui.terminal.mouse import CosmosLinuxDriver

        path = Path(path).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            raise ValueError("Unsupported Reader file: " + str(path))
        self.mouse_mode = mouse_mode
        super().__init__(ansi_color=True, driver_class=CosmosLinuxDriver)
        self.title = "Reader · " + path.name
        state = dict(path=str(path), page=1, zoom=1, pan=[0, 0], query="", thumbnails=True)
        wire = base64.b64encode(json.dumps(state).encode()).decode()
        self.panes = [Pane("reader", 0, 0, 80, 24, True, [], wire, (0, 0), cursor_visible=False)]
        self.lines, self.views = {}, []
        self.settings, self.role_colors = {}, dict(DARK)
        self.prefix, self.closing, self.message = False, False, ""
        self._workspace_screen, self._cursor_mode = None, None
        self._surface_state, self._status_text = None, None
        self.ui_registry = UIRegistry()
        self.backend = SimpleNamespace(session_id=None)
        self.graphics = Graphics()
        self.reader_ui = ReaderController(self)
        self.output = OutputController(self)

    def compose(self):
        yield TerminalSurface(id="terminal")
        yield Static("Reader · q quit · ? help", id="status", markup=False)

    def active(self):
        return self.panes[0]

    async def on_mount(self):
        self._workspace_screen = self.screen
        self.query_one(TerminalSurface).focus()
        self.set_interval(0.1, self.tick)
        await self.tick()

    async def tick(self):
        if self.closing:
            return
        surface = self.query_one(TerminalSurface)
        if surface.size.width < 1 or surface.size.height < 2:
            return
        pane = replace(self.active(), width=surface.size.width, height=surface.size.height)
        self.panes[0] = pane
        self.reader_ui.sync_visible(self.panes)
        frame = self.reader_ui.loading.frame(pane)
        self.lines = {pane.id: frame.lines}
        visible = self.screen is self._workspace_screen or getattr(self.screen, "preserve_workspace_graphics", False)
        image = frame.image
        cover = getattr(self.screen, "cover_reader_image", None)
        if cover:
            image = cover(image, pane)
        self.graphics.commit([(pane.id, image, 0, 0)] if self.graphics.enabled and visible else [])
        state = pane.width, pane.height, frame.lines
        if state != self._surface_state:
            self._surface_state = state
            surface.refresh()
        if self.graphics.pending:
            self.call_after_refresh(self.output.flush_graphics)
        status = self.message or "Reader · q quit · ? help"
        if status != self._status_text:
            self._status_text = status
            self.query_one("#status", Static).update(status)

    async def save_reader_state(self, pane, wire):
        pane.viewer = wire
        if not wire:
            self.closing = True
            self.exit()

    async def action_error(self, command, error, **kwargs):
        self.message = str(error)

    async def on_key(self, event):
        if self.screen is self._workspace_screen:
            await self.reader_ui.on_key(event, self.active())
            event.stop()

    async def on_mouse_down(self, event):
        await self.reader_ui.on_mouse_down(event)

    async def on_mouse_move(self, event):
        await self.reader_ui.on_mouse_move(event)

    def on_mouse_up(self, event):
        self.reader_ui.on_mouse_up(event)

    async def on_mouse_scroll_up(self, event):
        await self.reader_ui.scroll_viewer(event, -1)

    async def on_mouse_scroll_down(self, event):
        await self.reader_ui.scroll_viewer(event, 1)

    def on_resize(self, event):
        self.output.on_resize(event)

    def _display_native(self, screen, renderable):
        super()._display(screen, renderable)

    def _display(self, screen, renderable):
        self.output._display(screen, renderable)

    def render_background(self, rect, y):
        return self.query_one(TerminalSurface).render_line(rect.y + y).crop(rect.x, rect.x + rect.width)

    def check_action(self, action, parameters):
        if action in {"leader", "leader_key"}:
            return False
        return super().check_action(action, parameters)

    async def on_unmount(self):
        self.closing = True
        await self.reader_ui.close()
        self.graphics.commit([])
        self.output.flush_graphics()


def run(path, *, mouse_mode="auto"):
    ReaderApp(path, mouse_mode=mouse_mode).run()
