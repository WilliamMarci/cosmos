from __future__ import annotations
import asyncio
import logging
import base64
import json
import os
import shutil
import fcntl
import termios
import struct
import sys
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.geometry import Offset
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Static
from textual._compositor import CompositorUpdate
from .backend import Tmux
from .borders import borders
from .terminal_grid import decode_grid
from . import keymap
from .key_settings import KeyBindingEditor
from .ui import UIRegistry
from .notifications import NoticeToast
from .menus import CompactMenu
from .presentation import (
    SessionWindows,
    PopWindows,
    NotificationEvents,
    PowerlineSlot,
    PowerlineValue,
)
from .media import Media
from .reading import Reader
from .chrome import Frame
from .rendering import Batch, Graphics
from . import rpc
from .switcher import Switcher
from .assistant import Assistant
from .agent_bridge import AgentBridge
from .surfaces import Zone
from .shortcuts import (
    CosmosInput,
    CosmosModal,
    leader_bindings,
    leader_key,
    MODIFIER_KEYS,
)

DARK = dict(
    bg="#14161e",
    base="#1e212c",
    fg="#cdd2dc",
    mute="#7a8092",
    acc="#62a0e6",
    accl="#a0cdfa",
    on="#10121a",
)
LIGHT = dict(
    bg="#f2f4f9",
    base="#e6eaf2",
    fg="#232b3a",
    mute="#5f6b80",
    acc="#2e6bb4",
    accl="#195295",
    on="#fafcff",
)
WORKSPACE = [
    ("Leader p", "command palette"),
    ("Leader a", "terminal_agent"),
    ("Leader g", "split OpenCode"),
    ("Leader s", "switch session / window"),
    ("Leader c", "create window"),
    ("Leader %", "split left / right"),
    ('Leader "', "split top / bottom"),
    ("Leader arrows / o", "focus pane"),
    ("Leader H / J / K / L", "resize pane by 5 cells"),
    ("Leader | / -", "split left-right / top-bottom"),
    ("Leader n / b", "next / previous window"),
    ("Leader z", "zoom pane"),
    ("Leader d", "detach"),
    ("Leader Leader", "send literal Leader"),
]
VIEWER = [
    ("q / Esc", "close viewer"),
    ("+ / −", "zoom"),
    ("0", "fit"),
    ("arrows", "pan"),
    ("[ / ]", "previous / next page"),
    ("/", "search"),
    ("t", "collapse / expand thumbnails"),
    ("Click thumbnail", "select image / page"),
    ("Drag", "pan"),
    ("Ctrl + wheel", "zoom at pointer"),
    ("Enter / Esc", "confirm / cancel search"),
]
PANEL = [
    ("↑ / ↓", "choose action"),
    ("Enter", "confirm"),
    ("Esc", "cancel / back"),
    ("Type", "filter actions"),
]


class TerminalSurface(Widget):
    zone = Zone.SESSION_WINDOW
    can_focus = True

    def render_line(self, y):
        width = self.size.width
        palette = self.app.role_colors
        style = Style(color=palette["fg"], bgcolor=palette["bg"])
        border_row = borders(
            width,
            self.size.height,
            tuple((p.x, p.y, p.width, p.height, p.active) for p in self.app.panes),
        ).get(y, {})

        def gutter(left, right):
            segments = []
            for column in range(left, right):
                glyph, active = border_row.get(column, (" ", False))
                segments.append(
                    Segment(
                        glyph,
                        Style(
                            color=palette["acc"] if active else palette["mute"],
                            bgcolor=palette["bg"],
                        ),
                    )
                )
            return Strip(segments)

        parts = []
        x = 0
        for pane in sorted(self.app.panes, key=lambda p: p.x):
            if not pane.y <= y < pane.y + pane.height:
                continue
            if pane.x > x:
                parts.append(gutter(x, pane.x))
            lines = self.app.lines.get(pane.id, [])
            row = y - pane.y
            text = lines[row] if row < len(lines) else Text("", style=style)
            text = text.copy()
            text.stylize_before(style)
            strip = (
                Strip(
                    Segment(segment.text, segment.style or style, segment.control)
                    for segment in text.render(self.app.console, end="")
                )
                .crop(0, pane.width)
                .extend_cell_length(pane.width, style)
            )
            parts.append(strip)
            x = pane.x + pane.width
        if x < width:
            parts.append(gutter(x, width))
        strip = Strip.join(parts).crop(0, width)
        for layer in self.app.views:
            view = layer["view"]
            rect = layer["rect"]
            if not rect["y"] <= y < rect["y"] + rect["height"]:
                continue
            row = y - rect["y"]
            content = view["content"]
            items = [
                {"text": content.get("title", ""), "role": "acc"},
                *content.get("lines", []),
            ]
            item = items[row] if row < len(items) else {"text": "", "role": "fg"}
            rendered = Text(
                item["text"],
                style=Style(
                    color=palette.get(item["role"], palette["fg"]),
                    bgcolor=palette["base"],
                ),
            )
            overlay = (
                Strip(
                    Segment(s.text, s.style or style, s.control)
                    for s in rendered.render(self.app.console, end="")
                )
                .crop(0, rect["width"])
                .extend_cell_length(rect["width"], Style(bgcolor=palette["base"]))
            )
            strip = Strip.join(
                [
                    strip.crop(0, rect["x"]),
                    overlay,
                    strip.crop(rect["x"] + rect["width"], width),
                ]
            ).crop(0, width)
        return strip


class Help(CosmosModal):
    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("question_mark", "dismiss", show=False),
    ]

    def __init__(self, title, items):
        super().__init__()
        self.heading = title
        self.items = items

    def compose(self):
        text = Text(self.heading + "\n\n", style="bold")
        for key, label in self.items:
            text.append(f"{key:<19}", style="bold #a0cdfa")
            text.append(label + "\n", style="#cdd2dc")
        yield Static(text, id="help-content")


class Palette(CosmosModal):
    zone = Zone.POP_WINDOW
    BINDINGS = [Binding("escape", "back", show=False)]

    def __init__(self):
        super().__init__()
        self.menu = "actions"
        self.stack = []
        self.rows = []

    def compose(self):
        with Frame(id="palette") as frame:
            frame.border_title = "Cosmos / actions"
            yield CosmosInput(placeholder="", id="filter")
            yield ListView(id="actions")

    async def on_mount(self):
        await self.populate()
        self.query_one(Input).focus()

    async def populate(self):
        query = self.query_one(Input).value.casefold()
        snapshot = await rpc.call("state.snapshot")
        actions = snapshot["actions"]
        rows = [a for a in actions if a.get("category") == self.menu]
        if self.menu == "keys":
            settings = snapshot.get("settings", getattr(self.app, "settings", {}))
            rows.extend(
                dict(
                    label=f"{command.context} · {command.label}  {', '.join(keymap.bindings(command, settings))}",
                    kind="keybinding",
                    command=command,
                )
                for command in keymap.COMMANDS
            )
        if self.menu == "mods":
            rows += [
                dict(
                    label=f"{m['id']} · {m['status']['state']}",
                    kind="rpc",
                    method="mods.stop"
                    if m["status"]["state"]
                    in ("ready", "starting", "running", "backoff")
                    else "mods.start",
                    params={"id": m["id"], "client": self.app.client},
                )
                for m in snapshot["mods"]
            ]
        if self.menu == "actions":
            rows.extend(
                [
                    dict(label="Command assistant", kind="local", key="a"),
                    dict(label="OpenCode · split", kind="local", key="g"),
                ]
            )
        self.rows = [a for a in rows if query in a["label"].casefold()]
        listing = self.query_one(ListView)
        await listing.clear()
        await listing.extend(ListItem(Label(row["label"])) for row in self.rows)
        if self.rows:
            listing.index = 0
        self.query_one("#palette", Frame).border_title = "Cosmos / " + self.menu

    async def on_input_changed(self, event):
        await self.populate()

    async def on_input_submitted(self, event):
        await self.invoke()

    async def on_list_view_selected(self, event):
        await self.invoke()

    async def on_key(self, event):
        if event.key in ("up", "down"):
            listing = self.query_one(ListView)
            if self.rows:
                listing.index = max(
                    0,
                    min(
                        len(self.rows) - 1,
                        (listing.index or 0) + (1 if event.key == "down" else -1),
                    ),
                )
            event.stop()
            event.prevent_default()

    async def invoke(self):
        index = self.query_one(ListView).index
        if index is None or index >= len(self.rows):
            return
        row = self.rows[index]
        if row["kind"] == "local":
            self.dismiss()
            self.app.call_after_refresh(self.app.action_leader_key, row["key"])
            return
        if row["kind"] == "menu":
            self.stack.append(self.menu)
            self.menu = row["menu"]
            self.query_one(Input).value = ""
            await self.populate()
            return
        try:
            if row.get("method") in ("mods.start", "mods.stop"):
                await rpc.call(row["method"], row["params"])
            elif row.get("kind") == "rpc" and "id" not in row:
                await rpc.call(row["method"], row.get("params", {}))
            else:
                await rpc.call(
                    "actions.invoke",
                    {"id": row["id"], "params": {"client": self.app.client}},
                )
            await self.populate()
        except Exception as error:
            self.app.message = str(error)

    async def action_back(self):
        if self.stack:
            self.menu = self.stack.pop()
            self.query_one(Input).value = ""
            await self.populate()
        else:
            self.dismiss()


class Cosmos(App, inherit_bindings=False):
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: #14161e; color: #cdd2dc; }
    TerminalSurface { width: 100%; height: 1fr; overflow: hidden; }
    #status { height: 1; background: #1e212c; }
    #agent-powerline { layer: notices; position: absolute; height: 1; width: 100%; background: #1e212c; color: #7a8092; }
    #notice { layer: notices; position: absolute; width: auto; max-width: 60; height: 1; background: #1e212c; color: #e8a662; align-horizontal: right; }
    Assistant { background: transparent; background-tint: transparent; }
    Help, Palette { align: center middle; background: transparent; }
    #help-content { width: 72; max-width: 90%; height: auto; max-height: 90%; background: #1e212c; padding: 1 2; }
    #palette { width: 72; max-width: 90%; height: 70%; }
    #palette-title { height: 1; color: #a0cdfa; }
    Input { border: none; background: #1e212c; padding: 0; height: 1; }
    ListView { background: #1e212c; height: 1fr; margin-top: 1; }
    ListItem { height: 1; }
    ListItem > Label { padding: 0; }
    ListView > ListItem.--highlight { background: #62a0e6; color: #10121a; }
    """
    BINDINGS = leader_bindings()

    def __init__(self, session="main"):
        super().__init__()
        self.backend = Tmux(session)
        self.agent_bridge = None
        self._agent_registered = set()
        self.agent_prompt = ""
        self.assistant_passive = None
        self._passive_state = None
        self.panes = []
        self.lines = {}
        self.views = []
        self.view_focus = None
        self.graphics = Graphics()
        self.media = Media()
        self.reader = Reader(self.media)
        self.reader_frames = {}
        self._pixel_cell = None
        self._viewer_revision = {}
        self._viewer_drag = None
        self.prefix = False
        self.message = ""
        self.client = f"textual-{os.getpid()}"
        self.settings = {"theme": "dark", "leader": "C-b", "status_visible": True}
        self.role_colors = DARK
        self.busy = False
        self.viewer_pages = {}
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
        self.notification_events = NotificationEvents()
        self.powerline = PowerlineSlot()

    async def on_event(self, event):
        # Resolve Leader before forwarding to focused widgets. Keyboard protocols
        # may describe shifted punctuation by character rather than binding name.
        if isinstance(event, events.Key) and not event.is_forwarded:
            if event.key in MODIFIER_KEYS:
                return
            leader = "ctrl+a" if self.settings["leader"] == "C-a" else "ctrl+b"
            if event.key == leader:
                await self.action_leader(leader)
                return
            if self.prefix:
                key = leader_key(event.key, event.character)
                context = self.key_context()
                command = keymap.resolve(context, "leader+" + key, self.settings)
                if command:
                    if command.context.startswith("assistant") and isinstance(
                        self.screen, Assistant
                    ):
                        self.prefix = False
                        await self.screen.run_action(command.target)
                    else:
                        await self.action_leader_key(command.target)
                else:
                    self.prefix = False
                    logging.getLogger(__name__).debug(
                        "unmapped Leader key %s", event.key
                    )
                return
        if isinstance(event, events.Key) and not event.is_forwarded:
            context = self.key_context()
            if context != "workspace" and not (
                context == "viewer" and self.search is not None
            ):
                key = leader_key(event.key, event.character)
                command = keymap.resolve(context, key, self.settings)
                if command and command.context.startswith("assistant"):
                    await self.screen.run_action(command.target)
                    return
                if command:
                    canonical = command.target
                    character = canonical if len(canonical) == 1 else None
                    event = events.Key(canonical, character)
                elif keymap.default_reserved(context, key):
                    return
        if (
            isinstance(event, events.Key)
            and not event.is_forwarded
            and isinstance(self.screen, Switcher)
        ):
            self.screen.set_focus(self.screen.query_one(Input))
        await super().on_event(event)

    def key_context(self):
        if not self._screen_stack:
            return "workspace"
        if isinstance(self.screen, Assistant):
            return "assistant_actions" if self.screen.actions_mode else "assistant"
        if isinstance(self.screen, KeyBindingEditor):
            return "key_settings"
        if isinstance(self.screen, Switcher):
            return "switch"
        if isinstance(self.screen, Palette):
            return "palette"
        if isinstance(self.screen, CompactMenu):
            return "menu"
        if isinstance(self.screen, Help):
            return "help"
        if self.view_focus is not None:
            return "surface"
        pane = self.active()
        return (
            ("viewer_search" if self.search is not None else "viewer")
            if pane and pane.viewer
            else "workspace"
        )

    def render_background(self, rect, y):
        return (
            self.query_one(TerminalSurface)
            .render_line(rect.y + y)
            .crop(rect.x, rect.x + rect.width)
        )

    def compose(self) -> ComposeResult:
        yield TerminalSurface(id="terminal")
        yield Static("", id="agent-powerline", markup=False)
        yield Static("", id="status")
        yield NoticeToast(id="notice")

    def push_screen(self, *args, **kwargs):
        self.graphics.commit([])
        return super().push_screen(*args, **kwargs)

    def cursor_mode(self):
        if self.closing:
            return (True, 0)
        pane = self.active()
        visible = bool(
            pane
            and self.screen is self._workspace_screen
            and not pane.viewer
            and not self.views
            and pane.cursor_visible
        )
        if not visible:
            return (False, 0)
        shape = pane.cursor_shape
        # Default follows the terminal's usual blinking block; explicit VT styles
        # from applications retain their steady/blinking choice.
        blinking = shape == "default" or pane.cursor_blinking
        style = {"block": 1, "underline": 3, "bar": 5}.get(shape, 1) + (not blinking)
        return (True, style)

    def _display(self, screen, renderable):
        # Textual drops writes during a batch/startup. Retain graphics packets
        # until the driver can actually accept the compositor update.
        writable = (
            self._running
            and not self._closed
            and not self.is_headless
            and self._driver is not None
            and not self._batch_count
        )
        if not writable:
            return super()._display(screen, renderable)
        if isinstance(renderable, CompositorUpdate):
            mode = self.cursor_mode()
            control = ""
            if mode != self._cursor_mode:
                visible, style = mode
                control = (
                    (
                        f"\x1b[{style} q"
                        + ("\x1b[?12h" if style % 2 or style == 0 else "\x1b[?12l")
                        + "\x1b[?25h"
                    )
                    if visible
                    else "\x1b[?25l"
                )
                if (
                    self._running
                    and not self._closed
                    and not self.is_headless
                    and self._driver is not None
                    and not self._batch_count
                ):
                    self._cursor_mode = mode
            renderable = Batch(renderable, self.graphics.take() + control)
        super()._display(screen, renderable)

    def flush_graphics(self):
        if self.graphics.pending and not self.is_headless:
            self._display(self.screen, Batch())

    async def on_mount(self):
        self._workspace_screen = self.screen
        self.agent_bridge = AgentBridge(self)
        await self.agent_bridge.start()
        await self.backend.connect()
        await rpc.call(
            "ui.attach",
            {
                "client": self.client,
                "width": max(1, self.size.width),
                "height": max(1, self.size.height),
            },
        )
        self.query_one("#agent-powerline").display = False
        self.query_one(TerminalSurface).focus()
        self.set_interval(0.1, self.tick)
        await self.tick()

    def check_action(self, action, parameters):
        if action == "leader_key":
            return self.prefix
        if action == "leader":
            return parameters[0] == (
                "ctrl+a" if self.settings["leader"] == "C-a" else "ctrl+b"
            )
        return True

    async def action_leader(self, key):
        logging.getLogger(__name__).debug("action_leader %s", key)
        if self.prefix:
            self.prefix = False
            await self.backend.send(key)
        else:
            self.prefix = True

    async def action_leader_key(self, key):
        logging.getLogger(__name__).debug("action_leader_key %s", key)
        self.prefix = False
        if key == "d":
            await self.detach()
            return
        if key == "a":
            pane = self.active()
            if pane and self.screen is self._workspace_screen:
                ready = await self.backend.request(
                    f"show-options -pqv -t {pane.id} @cosmos_terminal_agent"
                )
                program = await self.backend.request(
                    f"display-message -p -t {pane.id} '#{{pane_current_command}}'"
                )
                if program != ["bash"]:
                    self.message = (
                        "Return this pane to Bash to open the command assistant"
                    )
                    return
                if ready != ["1"]:
                    self.message = "Source terminal_agent/shell/agent.bash in this Bash, or create a new pane"
                    return
                await self.backend.request(
                    f"set-option -p -t {pane.id} @cosmos_agent_socket {self.backend.quote(self.agent_bridge.path)}"
                )
                await self.backend.request(f"send-keys -t {pane.id} C-x C-a")
            return
        if key == "g":
            executable = shutil.which(os.getenv("COSMOS_OPENCODE", "opencode"))
            if not executable:
                self.message = "OpenCode not found on PATH"
                return
            arguments = [executable]
            if self.agent_prompt:
                arguments += ["--prompt", self.agent_prompt]
            self.agent_prompt = ""
            pane = self.active()
            if pane:
                await self.session_windows.split(pane.id, arguments)
            self.panes = await self.backend.snapshot()
            return
        if key == "N":
            notices = await rpc.call("notifications.active", {"client": self.client})
            if notices:
                notice = notices[-1]
                choices = [(a["id"], a["label"]) for a in notice.get("actions", [])] + [
                    ("__dismiss__", "×  Dismiss here")
                ]

                def choose(action):
                    if action:
                        self.run_worker(
                            self.on_notice_toast_action(
                                NoticeToast.Action(notice["id"], action)
                            )
                        )

                self.pop_windows.actions("Notification", choices, choose)
            return
        if key == "full_stop":
            if isinstance(self.screen, Assistant):
                self.screen.action_actions()
            return
        if key == "s":
            self.push_screen(Switcher())
            return
        if key == "p":
            self.push_screen(Palette())
            return
        if key == "question_mark":
            if isinstance(self.screen, Assistant):
                self.push_screen(
                    Help(
                        "Command suggestions",
                        keymap.help_rows(self.key_context(), self.settings),
                    )
                )
                return
            if isinstance(self.screen, (Palette, CompactMenu)):
                self.push_screen(
                    Help("Actions", keymap.help_rows(self.key_context(), self.settings))
                )
                return
            if isinstance(self.screen, Switcher):
                self.push_screen(
                    Help(
                        "Switch",
                        keymap.help_rows("switch", self.settings)
                        + [("Type", "filter sessions / windows")],
                    )
                )
                return
            self.push_screen(
                Help(
                    "Viewer" if self.active() and self.active().viewer else "Workspace",
                    keymap.help_rows(
                        "viewer"
                        if self.active() and self.active().viewer
                        else "workspace",
                        self.settings,
                    ),
                )
            )
            return
        command = {
            "c": "new-window",
            "percent_sign": "split-window -h",
            "quotation_mark": "split-window -v",
            "vertical_line": "split-window -h",
            "minus": "split-window -v",
            "H": "resize-pane -L 5",
            "J": "resize-pane -D 5",
            "K": "resize-pane -U 5",
            "L": "resize-pane -R 5",
            "n": "next-window",
            "b": "previous-window",
            "o": "select-pane -t :.+",
            "z": "resize-pane -Z",
            "up": "select-pane -U",
            "down": "select-pane -D",
            "left": "select-pane -L",
            "right": "select-pane -R",
        }.get(key)
        if key.isdigit():
            command = f"select-window -t :{key}"
        if command:
            if self.screen is not self._workspace_screen:
                return
            pane = self.active()
            if pane and command.startswith(
                ("split-window", "select-pane", "resize-pane")
            ):
                name, _, arguments = command.partition(" ")
                command = f"{name} -t {pane.id} {arguments}"
            logging.getLogger(__name__).debug("layout %s", command)
            try:
                await self.backend.request(command)
                self.panes = await self.backend.snapshot()
            except RuntimeError as error:
                await self.action_error(command, error)

    async def action_error(self, command, error):
        # A rejected user operation is not a fatal frontend exception.
        text = " ".join(str(error).split())[:240] or "Operation failed"
        logging.getLogger(__name__).warning("operation %s failed: %s", command, text)
        self.message = text
        try:
            await rpc.call(
                "notifications.publish",
                {"text": text, "source": "workspace", "ttl_ms": 5000},
            )
        except (OSError, RuntimeError):
            logging.getLogger(__name__).warning("could not publish operation error")

    def active(self):
        return next((p for p in self.panes if p.active), None)

    async def detach(self, reason="detach"):
        self.closing = True
        self.graphics.commit([])
        self.flush_graphics()
        await self.backend.close()
        try:
            await rpc.call("ui.detach", {"client": self.client})
        except (OSError, RuntimeError):
            pass
        self.exit({"reason": reason, "session": self.backend.session})

    async def on_unmount(self):
        if self.agent_bridge:
            await self.agent_bridge.close()
        await self.backend.close()
        try:
            await rpc.call("ui.detach", {"client": self.client})
        except (OSError, RuntimeError):
            pass

    async def tick(self):
        if self.busy or self.closing:
            return
        self.busy = True
        try:
            await rpc.call("ui.heartbeat", {"client": self.client})
            self.settings = await rpc.call("settings.get")
            self.role_colors = LIGHT if self.settings["theme"] == "light" else DARK
            for frame in self.screen.query(Frame):
                frame.apply_theme(self.role_colors)
            terminal = self.query_one(TerminalSurface)
            status_widget = self.query_one("#status", Static)
            if status_widget.display != self.settings["status_visible"]:
                status_widget.display = self.settings["status_visible"]
            await self.backend.resize(
                max(1, terminal.size.width), max(1, terminal.size.height)
            )
            panes = await self.backend.snapshot()
            lines = {}
            images = []
            snapshot = await rpc.call("ui.snapshot", {"client": self.client})
            self.views = []
            self.status_widgets = []
            self.view_focus = None
            for layer in snapshot.get("views", []):
                view = layer["view"]
                if view["kind"] == "status_widget":
                    self.status_widgets.append(view)
                    continue
                if view["owner"] == "core":
                    continue
                target = view.get("target")
                if target:
                    pane = next((p for p in panes if p.id == target), None)
                    if pane is None:
                        continue
                    layer["rect"] = {
                        "x": pane.x,
                        "y": pane.y,
                        "width": pane.width,
                        "height": pane.height,
                    }
                self.views.append(layer)
                if snapshot.get("focus") == view["id"] and (
                    not target or any(p.id == target and p.active for p in panes)
                ):
                    self.view_focus = view["id"]

            for pane in panes:
                lines[pane.id] = list(decode_grid(tuple(pane.lines)))
                if pane.viewer:
                    try:
                        state = json.loads(base64.b64decode(pane.viewer))
                        revision = self._viewer_revision.get(pane.id, 0)
                        source, pages, has_text = await asyncio.to_thread(
                            self.media.load, state
                        )
                        frame = await asyncio.to_thread(
                            self.reader.render,
                            source,
                            state,
                            pages,
                            pane.width,
                            pane.height,
                            self.cell_pixels(),
                            self.role_colors,
                            self.graphics.enabled,
                        )
                        if revision != self._viewer_revision.get(pane.id, 0):
                            return
                        self.reader_frames[pane.id] = frame
                        self.viewer_pages[pane.id] = pages
                        lines[pane.id] = frame.lines
                        if self.screen is self._workspace_screen and not self.views:
                            images.append((pane.id, frame.image, pane.x, pane.y))
                        if pane.active:
                            self.message = ""
                        if (
                            pane.active
                            and not has_text
                            and str(state["path"]).lower().endswith(".pdf")
                        ):
                            self.message = "No text layer; OCR is not enabled"
                    except Exception as error:
                        self.message = str(error)
            if self.search is not None:
                self.message = "/" + self.search
            self.panes, self.lines = panes, lines
            if self.agent_bridge:
                for source_pane in panes:
                    if source_pane.id not in self._agent_registered:
                        await self.backend.request(
                            f"set-option -p -t {source_pane.id} @cosmos_agent_socket {self.backend.quote(self.agent_bridge.path)}"
                        )
                        self._agent_registered.add(source_pane.id)
                self._agent_registered.intersection_update(p.id for p in panes)
            if isinstance(self.screen, Assistant):
                if any(p.id == self.screen.request["pane"] for p in panes):
                    self.screen.place()
                else:
                    await self.screen.action_cancel()
            passive = self.assistant_passive
            if passive and (
                not self.powerline.active
                or self.powerline.active.owner == "terminal_agent"
            ):
                self.powerline.publish(
                    PowerlineValue(
                        "terminal_agent", passive["pane"], passive["request"]
                    )
                )
            elif not passive:
                self.powerline.release("terminal_agent")
            lease = self.powerline.active
            passive = (
                dict(pane=lease.source_pane, request=lease.text) if lease else None
            )
            source = next(
                (p for p in panes if passive and p.id == passive["pane"] and p.active),
                None,
            )
            passive_state = (
                (
                    source.id,
                    passive["request"],
                    source.y + source.cursor[1],
                    terminal.size.height,
                )
                if source and self.screen is self._workspace_screen
                else None
            )
            if passive_state != self._passive_state:
                self._passive_state = passive_state
                bar = self.query_one("#agent-powerline", Static)
                bar.display = passive_state is not None
                if passive_state:
                    bar.styles.offset = (
                        0,
                        max(
                            0,
                            terminal.size.height
                            - (
                                2
                                if source.y + source.cursor[1]
                                >= terminal.size.height - 1
                                else 1
                            ),
                        ),
                    )
                    bar.update(" › " + passive["request"])
            self.graphics.commit(
                images
                if self.graphics.enabled and self.screen is self._workspace_screen
                else []
            )
            surface_state = (
                [(p.id, p.x, p.y, p.width, p.height, p.active) for p in panes],
                lines,
                self.views,
                self.role_colors,
            )
            if surface_state != self._surface_state:
                self._surface_state = surface_state
                terminal.refresh()
            if self.graphics.pending:
                self.call_after_refresh(self.flush_graphics)
            status = Text()
            for _, index, active, name in self.backend.tabs:
                if active == "1":
                    status.append(
                        f" {index} {name} ",
                        style=f"{self.role_colors['on']} on {self.role_colors['acc']}",
                    )
                    break
            for widget in self.status_widgets:
                for item in widget.get("content", {}).get("lines", [])[:1]:
                    status.append(
                        " " + item["text"] + " ",
                        style=self.role_colors.get(
                            item["role"], self.role_colors["mute"]
                        ),
                    )
            if status != self._status_content:
                self._status_content = status
                status_widget.update(status)
            notices = await rpc.call("notifications.active", {"client": self.client})
            for host in (self._workspace_screen, self.screen):
                if host:
                    for notice in host.query(NoticeToast):
                        notice.present_notice(
                            notices[-1] if notices else None,
                            self.size.width,
                            self.size.height,
                            self.role_colors,
                        )
            pane = self.active()
            # Modal inputs own the physical cursor. Polling a hidden shell must not
            # relocate its cursor into the switcher / restart input cursor painting.
            if pane and self.screen is self._workspace_screen:
                position = Offset(pane.x + pane.cursor[0], pane.y + pane.cursor[1])
                if self.cursor_position != position:
                    self.cursor_position = position
                    if not self.is_headless:
                        self._display(self.screen, Batch())
            if not self.is_headless and self.cursor_mode() != self._cursor_mode:
                self._display(self.screen, Batch())
        except EOFError:
            await self.detach("exit")
        except Exception as error:
            logging.getLogger(__name__).exception("UI refresh failed")
            self.message = str(error)
            status = Text(self.message, style="red")
            if status != self._status_content:
                self._status_content = status
                self.query_one("#status", Static).update(status)
        finally:
            self.busy = False

    async def on_notice_toast_action(self, event):
        event.stop()
        method = (
            "notifications.dismiss"
            if event.action == "__dismiss__"
            else "notifications.act"
        )
        try:
            await rpc.call(
                method,
                {
                    "id": event.notification,
                    "action": event.action,
                    "client": self.client,
                },
            )
        except RuntimeError as error:
            await self.action_error(method, error)

    def on_resize(self, event):
        pixels = event.pixel_size
        self._pixel_cell = (
            (
                max(1, round(pixels.width / event.size.width)),
                max(1, round(pixels.height / event.size.height)),
            )
            if pixels
            and pixels.width
            and pixels.height
            and event.size.width
            and event.size.height
            else None
        )

    def cell_pixels(self):
        if self._pixel_cell:
            return self._pixel_cell
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
        frame = self.reader_frames.get(pane.id)
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
        self._viewer_revision[pane.id] = self._viewer_revision.get(pane.id, 0) + 1
        await self.backend.request(f"set-option -p -t {pane.id} @cosmos_viewer {wire}")
        pane.viewer = wire

    def viewer_at(self, event):
        if self.screen is not self._workspace_screen:
            return None
        return next(
            (
                p
                for p in self.panes
                if p.viewer
                and p.x <= event.screen_x < p.x + p.width
                and p.y <= event.screen_y < p.y + p.height
            ),
            None,
        )

    async def on_mouse_down(self, event):
        if self.screen is self._workspace_screen and event.button == 1:
            target = next(
                (
                    p
                    for p in self.panes
                    if p.x <= event.screen_x < p.x + p.width
                    and p.y <= event.screen_y < p.y + p.height
                ),
                None,
            )
            if target and not target.active:
                await self.backend.request(f"select-pane -t {target.id}")
                self.panes = await self.backend.snapshot()
                self.query_one(TerminalSurface).focus()
                logging.getLogger(__name__).debug("mouse focus %s", target.id)
        pane = self.viewer_at(event)
        if not pane or event.button != 1:
            return
        frame = self.reader_frames.get(pane.id)
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
            self._viewer_drag = pane.id, event.screen_x, event.screen_y
            self.query_one(TerminalSurface).capture_mouse()

    async def on_mouse_move(self, event):
        if not self._viewer_drag:
            return
        pid, x, y = self._viewer_drag
        pane = next((p for p in self.panes if p.id == pid and p.viewer), None)
        if pane:
            frame = self.reader_frames.get(pid)
            state = json.loads(base64.b64decode(pane.viewer))
            cw, ch = self.cell_pixels()
            state["pan"] = [
                state["pan"][0]
                - (event.screen_x - x) * cw / self.view_scale(pane, state, frame),
                state["pan"][1]
                - (event.screen_y - y) * ch / self.view_scale(pane, state, frame),
            ]
            self._viewer_drag = pid, event.screen_x, event.screen_y
            await self.update_viewer(pane, state)
            event.stop()

    def on_mouse_up(self, event):
        if self._viewer_drag:
            self._viewer_drag = None
            self.query_one(TerminalSurface).release_mouse()
            event.stop()

    async def scroll_viewer(self, event, direction):
        pane = self.viewer_at(event)
        if not pane:
            return
        frame = self.reader_frames.get(pane.id)
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

    async def on_mouse_scroll_up(self, event):
        await self.scroll_viewer(event, -1)

    async def on_mouse_scroll_down(self, event):
        await self.scroll_viewer(event, 1)

    async def on_key(self, event: events.Key):
        if self.screen is not self._workspace_screen:
            return
        event.stop()
        event.prevent_default()
        if self.prefix:
            self.prefix = False
            if event.key == "escape":
                return
        pane = self.active()
        if (
            event.key == "enter"
            and pane
            and self.assistant_passive
            and self.assistant_passive["pane"] == pane.id
        ):
            self.assistant_passive = None
        if self.view_focus is not None:
            if event.key == "escape":
                await rpc.call(
                    "presentation.close",
                    {"client": self.client, "view": self.view_focus},
                )
            else:
                named = {
                    "enter": "enter",
                    "backspace": "backspace",
                    "up": "up",
                    "down": "down",
                    "left": "left",
                    "right": "right",
                    "home": "home",
                    "end": "end",
                    "pageup": "page_up",
                    "pagedown": "page_down",
                }
                if event.character and event.character.isprintable():
                    key = {"type": "char", "value": event.character}
                elif event.key.startswith("ctrl+") and len(event.key) == 6:
                    key = {"type": "ctrl", "value": ord(event.key[-1]) - 96}
                else:
                    key = {"type": named.get(event.key, "escape")}
                await rpc.call("input.send", {"client": self.client, "key": key})
            return
        if pane and pane.viewer:
            state = json.loads(base64.b64decode(pane.viewer))
            if self.search is not None:
                if event.key == "escape":
                    self.search = None
                elif event.key == "enter":
                    state["query"] = self.search
                    self.search = None
                elif event.key == "backspace":
                    self.search = self.search[:-1]
                elif event.character and len(self.search) < 8192:
                    self.search += event.character
                self.message = "/" + self.search if self.search is not None else ""
            elif event.key in ("q", "escape"):
                self._viewer_revision[pane.id] = (
                    self._viewer_revision.get(pane.id, 0) + 1
                )
                self.reader_frames.pop(pane.id, None)
                pane.viewer = ""
                await self.backend.request(
                    f"set-option -pu -t {pane.id} @cosmos_viewer"
                )
                return
            elif event.character == "?":
                self.push_screen(
                    Help("Viewer", keymap.help_rows("viewer", self.settings))
                )
                return
            elif event.character == "/":
                self.search = state.get("query", "")
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
                frame = self.reader_frames.get(pane.id)
                if frame:
                    state = self.reader.change(
                        state,
                        frame.selected + (1 if event.character == "]" else -1),
                        frame.entries,
                    )
            elif event.key in ("up", "down", "left", "right"):
                frame = self.reader_frames.get(pane.id)
                if frame:
                    i = 0 if event.key in ("left", "right") else 1
                    cw, ch = self.cell_pixels()
                    state["pan"][i] += (
                        4 * (cw if i == 0 else ch) / self.view_scale(pane, state, frame)
                    ) * (1 if event.key in ("right", "down") else -1)
            await self.update_viewer(pane, state)
        else:
            await self.backend.send(event.key, event.character)

    async def on_paste(self, event: events.Paste):
        if self.screen is self._workspace_screen:
            event.stop()
            if self.search is not None:
                self.search = (self.search + event.text)[:8192]
            elif not (self.active() and self.active().viewer):
                await self.backend.paste(event.text)
