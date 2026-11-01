from __future__ import annotations

import os

from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Static

from cosmos_tui.core.services import (
    NotificationEvents,
    PopWindows,
    PowerlineSlot,
    SessionWindows,
)
from cosmos_tui.features.assistant.launch import AssistantLauncher
from cosmos_tui.mods.manager import UIMods
from cosmos_tui.features.history.controller import HistoryController
from cosmos_tui.features.status.controller import StatusController
from cosmos_tui.features.ime.controller import IMEController
from cosmos_tui.features.navigation.controller import NavigationController
from cosmos_tui.features.navigation.menus import StatusBar
from cosmos_tui.features.notifications.controller import NotificationController
from cosmos_tui.features.notifications.toast import NoticeToast
from cosmos_tui.features.reader.controller import ReaderController
from cosmos_tui.features.settings.panel import Palette as Palette
from cosmos_tui.features.workspace.controller import WorkspaceController
from cosmos_tui.input.pointer import PointerRouter
from cosmos_tui.input.router import InputRouter
from cosmos_tui.input.shortcuts import leader_bindings
from cosmos_tui.render.graphics import Graphics
from cosmos_tui.render.output import OutputController
from cosmos_tui.render.surface import TerminalSurface as TerminalSurface
from cosmos_tui.runtime.coordinator import RuntimeController
from cosmos_tui.terminal.tmux import Tmux
from cosmos_tui.ui.cells import UIRegistry
from cosmos_tui.ui.help import Help as Help
from cosmos_tui.ui.logo import DEFAULT_LOGO
from cosmos_tui.ui.styles import DARK as DARK
from cosmos_tui.ui.styles import LIGHT as LIGHT
from cosmos_tui.ui.styles import WORKSPACE_CSS


class Cosmos(App, inherit_bindings=False):
    ENABLE_COMMAND_PALETTE = False
    CSS = WORKSPACE_CSS
    BINDINGS = leader_bindings()

    def __init__(self, session="main", *, mouse_mode="auto"):
        from cosmos_tui.terminal.mouse import CosmosLinuxDriver, MODES

        if mouse_mode not in MODES:
            raise ValueError("mouse_mode must be auto, cell or pixel")
        self.mouse_mode = mouse_mode
        super().__init__(ansi_color=True, driver_class=CosmosLinuxDriver)
        self.backend = Tmux(session)
        self.panes = []
        self.lines = {}
        self.views = []
        self.view_focus = None
        self.graphics = Graphics()
        self.prefix = False
        self.message = ""
        self.client = f"textual-{os.getpid()}"
        self.settings = {
            "theme": "dark",
            "leader": "C-b",
            "status_visible": True,
            "mouse_passthrough": True,
        }
        self.role_colors = DARK
        self.theme_is_light = False
        self.theme_logo = DEFAULT_LOGO
        self.busy = False
        self.search = None
        self.closing = False
        self._workspace_screen = None
        self._cursor_mode = None
        self._surface_state = None
        self._status_content = None
        self._notice_state = None
        self.ui_registry = UIRegistry()
        self.session_windows = SessionWindows(self.backend)
        self.pop_windows = PopWindows(self)
        self.notification_events = NotificationEvents(self)
        self.powerline = PowerlineSlot()
        self.ui_mods = UIMods(self)

        self.runtime = RuntimeController(self)
        self.inputs = InputRouter(self)
        self.ime = IMEController(self)
        self.status = StatusController(self)
        self.output = OutputController(self)
        self.navigation = NavigationController(self)
        self.reader_ui = ReaderController(self)
        self.history_ui = HistoryController(self)
        self.notifications_ui = NotificationController(self)
        self.pointer = PointerRouter(self)
        self.workspace = WorkspaceController(self)
        self.assistant_ui = AssistantLauncher(self)

    def render_background(self, rect, y):
        return (
            self.query_one(TerminalSurface)
            .render_line(rect.y + y)
            .crop(rect.x, rect.x + rect.width)
        )

    def compose(self) -> ComposeResult:
        yield TerminalSurface(id="terminal")
        yield Static("", id="agent-powerline", markup=False)
        yield StatusBar(" COSMOS ", id="status")
        yield NoticeToast(id="notice")

    def push_screen(self, *args, **kwargs):
        screen = args[0] if args else kwargs.get("screen")
        if not getattr(screen, "preserve_workspace_graphics", False):
            self.graphics.commit([])
        return super().push_screen(*args, **kwargs)

    def set_mouse_mode(self, mode):
        from cosmos_tui.terminal.mouse import MODES

        if mode not in MODES:
            raise ValueError("mouse_mode must be auto, cell or pixel")
        self.mouse_mode = mode
        apply = getattr(self._driver, "apply_mouse_mode", None)
        if apply:
            apply()

    def active(self):
        return next((p for p in self.panes if p.active), None)

    async def _dispatch_native(self, event):
        await super().on_event(event)

    def _display_native(self, screen, renderable):
        return super()._display(screen, renderable)

    async def on_mount(self):
        return await self.runtime.on_mount()

    async def on_unmount(self):
        return await self.runtime.on_unmount()

    async def tick(self):
        return await self.runtime.tick()

    async def detach(self, reason="detach"):
        return await self.runtime.detach(reason)

    async def action_error(self, command, error, *, session_id=None):
        return await self.runtime.action_error(command, error, session_id=session_id)

    async def _guard_backend(self, operation):
        """Turn a dead Tmux control connection into a clean detach, not a crash."""
        try:
            return await operation()
        except EOFError:
            return await self.runtime.detach("exit")

    async def on_event(self, event):
        return await self._guard_backend(lambda: self.inputs.on_event(event))

    def key_context(self):
        return self.inputs.key_context()

    def check_action(self, action, parameters):
        return self.inputs.check_action(action, parameters)

    async def action_leader(self, key):
        return await self.inputs.action_leader(key)

    async def action_leader_key(self, key):
        return await self.workspace.action_leader_key(key)

    async def on_key(self, event: events.Key):
        return await self._guard_backend(lambda: self.inputs.on_key(event))

    async def on_paste(self, event: events.Paste):
        return await self._guard_backend(lambda: self.inputs.on_paste(event))

    def cursor_mode(self):
        return self.output.cursor_mode()

    def _display(self, screen, renderable):
        return self.output._display(screen, renderable)

    def flush_graphics(self):
        return self.output.flush_graphics()

    def on_resize(self, event):
        return self.output.on_resize(event)

    def action_context_actions(self):
        return self.navigation.action_context_actions()

    def action_start_menu(self):
        return self.navigation.action_start_menu()

    async def invoke_entry(self, row, source):
        return await self.navigation.invoke_entry(row, source)

    def open_pdf_search(self, pane, state):
        return self.reader_ui.open_pdf_search(pane, state)

    def cell_pixels(self):
        return self.reader_ui.cell_pixels()

    def view_scale(self, pane, state, frame):
        return self.reader_ui.view_scale(pane, state, frame)

    async def update_viewer(self, pane, state):
        return await self.reader_ui.update_viewer(pane, state)

    def viewer_at(self, event):
        return self.reader_ui.viewer_at(event)

    async def on_mouse_down(self, event):
        return await self._guard_backend(lambda: self.pointer.on_mouse_down(event))

    async def on_mouse_move(self, event):
        return await self._guard_backend(lambda: self.pointer.on_mouse_move(event))

    async def on_mouse_up(self, event):
        return await self._guard_backend(lambda: self.pointer.on_mouse_up(event))

    async def scroll_viewer(self, event, direction):
        return await self.reader_ui.scroll_viewer(event, direction)

    async def copy_action(self, command):
        return await self.history_ui.copy_action(command)

    async def scroll_history(self, event, up):
        return await self.history_ui.scroll_history(event, up)

    async def on_notice_toast_action(self, event):
        return await self.notifications_ui.on_notice_toast_action(event)

    async def on_mouse_scroll_up(self, event):
        return await self._guard_backend(
            lambda: self.pointer.on_mouse_scroll_up(event)
        )

    async def on_mouse_scroll_down(self, event):
        return await self._guard_backend(
            lambda: self.pointer.on_mouse_scroll_down(event)
        )
