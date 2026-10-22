"""Floating island presenter; original terminal_agent owns generation/history."""

import asyncio
import logging
import math
import time

from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput
from terminal_agent.backend import Demo, OpenCode
from terminal_agent.cosmos_bridge import restore, snapshot
from terminal_agent.ui import InlineUI
from textual.binding import Binding

from cosmos_tui.core import rpc
from cosmos_tui.features.assistant.layout import IslandViewState, layout_island
from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.cell_surface import CellSurface
from cosmos_tui.ui.cells import (
    CellRun,
    HitRegion,
    Rect,
    UIFrame,
    UIRegistry,
    cell_width,
    clip,
)
from cosmos_tui.ui.chrome import DEFAULT
from cosmos_tui.ui.editor import CellEditor
from cosmos_tui.ui.menus import CompactMenu
from cosmos_tui.ui.theme import assistant_roles, blend
from cosmos_tui.ui.zones import Zone
from terminal_agent.config import load


class ContextBackend:
    def __init__(self, backend, cwd):
        self.backend, self.cwd = backend, cwd

    async def propose(self, history):
        return await self.backend.propose(history, cwd=self.cwd)


class GuardedBackend:
    def __init__(self, presenter, backend):
        self.presenter, self.backend = presenter, backend

    async def propose(self, history):
        version = self.presenter.request_version
        result = await self.backend.propose(history)
        pane = self.presenter.source()
        if (
            self.presenter.finished
            or version != self.presenter.request_version
            or not pane
            or not pane.active
        ):
            raise asyncio.CancelledError()
        return result


class PresenterCallbacks:
    def __init__(self, presenter):
        self.presenter = presenter

    def invalidate(self):
        if not self.presenter.finished:
            self.presenter.sync()

    def exit(self, result):
        if not self.presenter.finished:
            self.presenter.view.completion_timestamp = time.monotonic()
            self.presenter.finish(result[0])


class ActionMenu(CompactMenu):
    def __init__(self, available):
        labels = {
            "agent": "a  OpenCode",
            "cancel": "×  Close",
            "run": "↵  Run current command",
        }
        super().__init__("Actions", [(action, labels[action]) for action in available])


class Assistant(CosmosModal):
    zone = Zone.INSERT_COVER
    DEFAULT_CSS = """
    Assistant { background: transparent; background-tint: transparent; }
    #assistant-input { position: absolute; width: 24; height: 1; background: transparent; }
    """
    BINDINGS = [
        Binding("escape,ctrl+c,ctrl+q", "cancel", show=False, priority=True),
        Binding("tab,shift+tab", "edit", show=False, priority=True),
        Binding("up", "recall(-1)", show=False, priority=True),
        Binding("down", "recall(1)", show=False, priority=True),
        Binding("left", "cycle(-1)", show=False, priority=True),
        Binding("right", "cycle(1)", show=False, priority=True),
        Binding("enter", "submit", show=False, priority=True),
        Binding("ctrl+g", "agent", show=False, priority=True),
    ]

    def __init__(self, request):
        super().__init__()
        self.request, self.job, self.finished = request, None, False
        engine = (
            Demo()
            if request.get("demo")
            else ContextBackend(
                OpenCode(request.get("config") or load()), request["cwd"]
            )
        )
        self.controller = InlineUI(
            GuardedBackend(self, engine),
            prompt=request.get("prompt", "$ "),
            shell_mode=True,
            input=DummyInput(),
            output=DummyOutput(),
        )
        restore(self.controller, request["state"])
        self.controller.app = PresenterCallbacks(self)
        meta = request["state"].get("cosmos_ui", {})
        self.interaction_id = request.get(
            "interaction_id", meta.get("interaction_id", "preview")
        )
        self.request_version = int(meta.get("request_version", 0))
        self.view = IslandViewState(
            measured_width=int(meta.get("width", 0)),
            completion_timestamp=float(meta.get("completed", 0)),
        )
        self.layout_data = None
        self.actions_mode = False
        self.mouse_inside = False
        self.hovered = None
        self.hover_suppressed = False
        self.hover_timer = self.leave_timer = self.animation = None
        self.owner = "assistant:" + self.interaction_id + ":" + str(id(self))
        self.registry = None
        self._placement_ready = False

    def compose(self):
        self.registry = getattr(self.app, "ui_registry", None) or UIRegistry()
        self.registry.attach(self.owner, Zone.INSERT_COVER, self.dispatch)
        yield CellSurface(self.registry, self.owner, id="assistant-face")
        yield CellEditor(id="assistant-input")

    def on_mount(self):
        self.origin_session = getattr(getattr(self.app, "backend", None), "session_id", None)
        self.registry.activate(self.owner)
        field = self.query_one(CellEditor)
        field.assign(
            self.controller.input.text, self.controller.input.buffer.cursor_position
        )
        self.sync(force=True)
        if not self.finished:
            field.focus()
        remaining = self.view.completion_timestamp + 0.6 - time.monotonic()
        if remaining > 0:
            self.set_timer(remaining, self.paint)

    def source(self):
        return next((p for p in self.app.panes if p.id == self.request["pane"]), None)

    def place(self):
        if self.finished:
            return
        pane = self.source()
        size = self.request.get("source_size")
        if pane and size and size != [pane.width, pane.height]:
            self.query_one(CellSurface).display = False
            self.query_one(CellEditor).display = False
            self.capture()
            self.finish("relocate")
            return
        command = self.request.get("source_command_rect")
        if not pane or not command:
            self.defer_close("Cannot locate the source command area")
            return
        rect = Rect(**command)
        roles = assistant_roles(getattr(self.app, "role_colors", DEFAULT))
        self.roles = roles
        signature = (
            pane.x,
            pane.y,
            pane.width,
            pane.height,
            tuple(command.items()),
            tuple(roles.items()),
            self.controller.input.text,
            self.controller.error,
            self.controller.busy,
            self.view.actions_visible,
            self.actions_mode,
            self.view.measured_width,
            self.reduced_motion,
        )
        if getattr(self, "_place_signature", None) == signature:
            return
        self._place_signature = signature
        if self.reduced_motion and self.animation:
            self.animation.stop()
            self.animation = None
        elif self.controller.busy and not self.reduced_motion and not self.animation:
            self.start_animation()
        editor = self.query_one(CellEditor)
        editor.roles = roles
        plan = layout_island(
            pane,
            rect,
            self.controller.input.text,
            self.view.actions_visible,
            bool(self.controller.error),
            self.view.measured_width,
        )
        if not plan:
            self.defer_close("Not enough space; returned to native editing")
            return
        if (
            self.controller.error
            and not plan.error
            and not getattr(self, "_notified_error", False)
        ):
            self._notified_error = True
            self.run_worker(self.notify(self.controller.error, level="error"))
        self.layout_data = plan
        editor.styles.width = max(1, plan.editor.width)
        editor.styles.offset = plan.editor.x, plan.editor.y
        editor.styles.height = 1
        editor.read_only = self.controller.busy or self.actions_mode
        editor.update_focus()
        self.paint()
        self._placement_ready = True

    def defer_close(self, message):
        if not getattr(self, "_close_pending", False):
            self._close_pending = True
            self.run_worker(self.notify(message))
            self.call_after_refresh(self.finish, "edit")

    async def notify(self, text, *, level="warning"):
        try:
            await rpc.call(
                "notifications.publish",
                {
                    "text": " ".join(text.split())[:240],
                    "source": "terminal_agent",
                    "level": level,
                    "session_id": getattr(self, "origin_session", None),
                },
            )
        except (OSError, RuntimeError, TimeoutError):
            logging.getLogger(__name__).warning("assistant notification unavailable")

    def enabled(self, action):
        return (
            action == "cancel"
            or not self.controller.busy
            and (action != "run" or bool(self.controller.command.text))
        )

    def paint(self, dirty=()):
        plan = self.layout_data
        if not plan or self.finished:
            return
        roles = self.roles
        runs = [CellRun(plan.input_surface, "", roles["text"], roles["surface"])]
        now = time.monotonic()
        if plan.status:
            glyph = (
                "!"
                if self.controller.error
                else "✓"
                if now - self.view.completion_timestamp < 0.6
                else "●"
            )
            color = (
                roles["error"]
                if self.controller.error
                else roles["success"]
                if glyph == "✓"
                else roles["muted"]
            )
            if self.controller.busy:
                glyph = "●"
                u = (
                    0
                    if self.reduced_motion
                    else (
                        1
                        - math.cos(
                            2 * math.pi * (now - self.view.generation_started_at) / 1.4
                        )
                    )
                    / 2
                )
                color = blend(roles["accent"], roles["accentStrong"], u)
            runs.append(CellRun(plan.status, glyph, color, roles["surface"]))
        hits = []
        for action, rect in plan.actions:
            enabled = self.enabled(action)
            selected = self.hovered == action or self.view.action_focus == action
            bg = roles["accentStrong"] if enabled and selected else roles["surface"]
            fg = roles["onAccent"] if enabled and selected else roles["muted"]
            label = {"agent": "a", "cancel": "×", "run": "↵"}[action]
            if cell_width(label) != 1:
                label = {"agent": "a", "cancel": "x", "run": ">"}[action]
            runs.append(
                CellRun(
                    rect,
                    " " + label + " ",
                    fg,
                    bg,
                    bold=self.view.action_focus == action,
                )
            )
            hits.append(HitRegion(action, rect, enabled))
        if plan.error:
            runs.append(
                CellRun(
                    plan.error,
                    " " + clip(self.controller.error, max(0, plan.error.width - 2)),
                    roles["error"],
                    roles["surface"],
                )
            )
        self.query_one(CellSurface).present(
            UIFrame(plan.bounds, tuple(runs), tuple(hits), tuple(dirty))
        )

    @property
    def reduced_motion(self):
        return bool(getattr(self.app, "settings", {}).get("reduced_motion", False))

    def sync(self, force=False):
        if self.finished or not self.is_mounted and not force:
            return
        field = self.query_one(CellEditor)
        if field.value != self.controller.input.text:
            field.assign(
                self.controller.input.text, self.controller.input.buffer.cursor_position
            )
        self.place()

    def capture(self):
        if not self.is_mounted:
            return
        field = self.query_one(CellEditor)
        self.controller.input.text = field.value
        self.controller.input.buffer.cursor_position = field.cursor_position

    def on_cell_editor_changed(self, event):
        self.capture()
        self.controller.error = ""
        self._notified_error = False
        if not self.actions_mode:
            self.view.actions_visible = False
            self.hover_suppressed = True
        self.sync()

    def dispatch(self, action):
        if not self.enabled(action):
            return
        if action == "cancel":
            self.run_worker(self.close())
        elif action == "agent":
            self.action_agent()
        elif action == "run":
            self.capture()
            self.finish("run")

    def action_submit(self):
        if self.actions_mode:
            self.dispatch(self.view.action_focus)
        elif not self.job and self.query_one(CellEditor).value.strip():
            self.capture()
            self.request_version += 1
            self.view.generation_started_at = time.monotonic()
            self.job = asyncio.create_task(self.generate(self.request_version))
            self.start_animation()

    async def generate(self, version):
        try:
            if version == self.request_version and not self.finished:
                await self.controller.generate()
        finally:
            self.job = None
            if self.animation:
                self.animation.stop()
                self.animation = None
            if not self.finished:
                self.sync()

    def start_animation(self):
        if self.animation:
            self.animation.stop()
        if not self.reduced_motion and self.job:
            self.animation = self.set_interval(1 / 12, self.animate)

    def animate(self):
        if self.app.screen is not self or not self.source():
            if self.animation:
                self.animation.pause()
            return
        plan = self.layout_data
        dirty = []
        if plan and self.controller.busy and plan.status:
            dirty.append(plan.status)
        if dirty:
            self.paint(dirty)
        elif self.animation:
            self.animation.stop()
            self.animation = None

    def on_screen_resume(self):
        if self.animation:
            self.animation.resume()

    def on_screen_suspend(self):
        if self.animation:
            self.animation.pause()

    def action_actions(self):
        self.capture()
        if not self.layout_data:
            return
        if not self.layout_data.can_expand:
            self.app.push_screen(
                ActionMenu([a for a in ("agent", "cancel", "run") if self.enabled(a)]),
                lambda action: self.dispatch(action) if action else None,
            )
            return
        self.actions_mode = True
        self.view.actions_visible = True
        self.view.action_focus = "run" if self.enabled("run") else "cancel"
        self.sync()

    def action_cycle(self, direction):
        if not self.actions_mode:
            field = self.query_one(CellEditor)
            event = type(
                "Key",
                (),
                {
                    "key": "left" if direction < 0 else "right",
                    "character": None,
                    "stop": lambda self: None,
                    "prevent_default": lambda self: None,
                },
            )()
            field.on_key(event)
            return
        choices = [a for a in ("agent", "cancel", "run") if self.enabled(a)]
        current = (
            choices.index(self.view.action_focus)
            if self.view.action_focus in choices
            else 0
        )
        self.view.action_focus = choices[(current + direction) % len(choices)]
        self.paint()

    async def action_cancel(self):
        if self.actions_mode:
            self.actions_mode = False
            self.view.action_focus = None
            self.view.actions_visible = False
            self.sync()
            self.query_one(CellEditor).focus()
            return
        await self.close()

    async def close(self):
        self.request_version += 1
        if self.job:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)
        self.capture()
        self.finish("cancel")

    def action_edit(self):
        if not self.job:
            self.capture()
            self.finish("edit")

    def action_recall(self, direction):
        if not self.job:
            self.capture()
            self.controller.recall_request(direction)
            self.view.measured_width = 0
            self.view.actions_visible = False
            self.hover_suppressed = True
            self.sync()

    def action_agent(self):
        if not self.job:
            self.capture()
            self.app.assistant_ui.prompt = (
                self.controller.command.text or self.controller.input.text
            )
            self.finish("edit")
            self.app.call_after_refresh(self.app.action_leader_key, "g")

    def on_mouse_move(self, event):
        plan = self.layout_data
        if not plan:
            return
        inside = plan.bounds.contains(event.screen_x, event.screen_y)
        if inside:
            if self.leave_timer:
                self.leave_timer.stop()
            if self.hover_suppressed:
                self.hover_suppressed = False
            if not self.mouse_inside or not self.view.actions_visible:
                if not self.hover_timer:
                    self.hover_timer = self.set_timer(0.18, self.show_actions)
        elif self.mouse_inside and not self.actions_mode:
            if self.hover_timer:
                self.hover_timer.stop()
                self.hover_timer = None
            self.leave_timer = self.set_timer(0.35, self.hide_actions)
        self.mouse_inside = inside
        hover = next(
            (
                a
                for a, r in plan.actions
                if r.contains(event.screen_x, event.screen_y) and self.enabled(a)
            ),
            None,
        )
        if hover != self.hovered:
            previous = self.hovered
            self.hovered = hover
            changed = [rect for name, rect in plan.actions if name in (hover, previous)]
            self.paint(changed)

    def show_actions(self):
        self.hover_timer = None
        if self.mouse_inside and not self.hover_suppressed:
            self.view.actions_visible = True
            self.sync()

    def hide_actions(self):
        if not self.actions_mode:
            self.view.actions_visible = False
            self.hovered = None
            self.sync()

    def on_mouse_scroll_up(self, event):
        if self.layout_data and self.layout_data.bounds.contains(
            event.screen_x, event.screen_y
        ):
            event.stop()

    on_mouse_scroll_down = on_mouse_scroll_up

    def finish(self, action):
        if not self.finished:
            if action != "update":
                self.capture()
            self.finished = True
            self.controller.cosmos_ui = dict(
                interaction_id=self.interaction_id,
                request_version=self.request_version,
                width=self.view.measured_width,
                completed=self.view.completion_timestamp,
            )
            self.dismiss(dict(action=action, state=snapshot(self.controller)))

    async def on_unmount(self):
        for timer in (
            self.animation,
            self.hover_timer,
            self.leave_timer,
        ):
            if timer:
                timer.stop()
        self.registry.detach(self.owner)
        if self.job:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)
