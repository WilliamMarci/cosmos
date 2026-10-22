"""Cosmos presenter for terminal_agent's existing controller and Readline protocol."""

import asyncio
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.widgets import Static
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput
from terminal_agent.ui import InlineUI
from terminal_agent.backend import OpenCode, Demo
from terminal_agent.config import load
from terminal_agent.cosmos_bridge import snapshot, restore
from .chrome import MiniAction, DEFAULT
from .surfaces import Zone, cover_rect
from .shortcuts import CosmosInput, CosmosModal


class ContextBackend:
    def __init__(self, backend, cwd):
        self.backend, self.cwd = backend, cwd

    async def propose(self, history):
        return await self.backend.propose(history, cwd=self.cwd)


class PresenterCallbacks:
    def __init__(self, presenter):
        self.presenter = presenter

    def invalidate(self):
        self.presenter.sync()

    def exit(self, result):
        self.presenter.finish(result[0])


class Assistant(CosmosModal):
    zone = Zone.INSERT_COVER
    DEFAULT_CSS = """
    Assistant { background: transparent; background-tint: transparent; }
    #assistant { width: 100%; height: auto; background: #1e212c; }
    #assistant-row { height: 1; }
    #assistant-status { width: 2; height: 1; }
    #assistant-indicator { width: 3; height: 1; }
    #assistant-input { width: 1fr; height: 1; padding: 0; }
    #assistant-error { height: auto; color: #e8a662; }
    """
    BINDINGS = [
        Binding("escape,ctrl+c,ctrl+q", "cancel", show=False),
        Binding("tab,shift+tab", "edit", show=False, priority=True),
        Binding("up", "recall(-1)", show=False, priority=True),
        Binding("down", "recall(1)", show=False, priority=True),
        Binding("ctrl+g", "agent", show=False, priority=True),
    ]

    def __init__(self, request):
        super().__init__()
        self.request = request
        self.job = None
        self.finished = False
        engine = (
            Demo()
            if request.get("demo")
            else ContextBackend(
                OpenCode(request.get("config") or load()), request["cwd"]
            )
        )
        self.controller = InlineUI(
            engine,
            prompt=request.get("prompt", "$ "),
            shell_mode=True,
            input=DummyInput(),
            output=DummyOutput(),
        )
        restore(self.controller, request["state"])
        # Never run prompt_toolkit's event loop or output driver inside Cosmos.
        self.controller.app = PresenterCallbacks(self)

    def compose(self):
        with Vertical(id="assistant"):
            with Horizontal(id="assistant-row"):
                yield Static("  ", id="assistant-status")
                yield Static(" › ", id="assistant-indicator")
                yield CosmosInput(id="assistant-input")
                yield MiniAction("ai", id="assistant-agent")
                yield MiniAction("×", id="assistant-cancel")
                yield MiniAction("↵", id="assistant-confirm")
            yield Static("", id="assistant-error", markup=False)

    def on_mount(self):
        self.place()
        self.sync(force=True)
        self.query_one(CosmosInput).focus()
        self.set_interval(0.08, self.animate_busy)

    def place(self):
        pane = next((p for p in self.app.panes if p.id == self.request["pane"]), None)
        if pane:
            box = self.query_one("#assistant")
            geometry = cover_rect(pane, 2 if self.controller.error else 1)
            if getattr(self, "_placement", None) != geometry:
                self._placement = geometry
                x, y, width, height = geometry
                below = pane.y + pane.cursor[1] + 1
                y = (
                    below
                    if below + height <= pane.y + pane.height
                    else max(pane.y, pane.y + pane.cursor[1] - height)
                )
                box.styles.width = width
                box.styles.offset = (x, y)

    def sync(self, force=False):
        if not self.is_mounted and not force:
            return
        field = self.query_one(CosmosInput)
        if field.value != self.controller.input.text:
            field.value = self.controller.input.text
            field.cursor_position = self.controller.input.buffer.cursor_position
        state = self.controller.state
        color = {
            "idle": "#7a8092",
            "busy": "#e8a662",
            "ready": "#8cbf80",
            "error": "#eb7080",
        }[state]
        self.query_one("#assistant-status").styles.background = color
        self.query_one("#assistant-indicator", Static).update(
            self.controller.indicator()
        )
        self.query_one("#assistant-confirm", MiniAction).disabled = (
            self.controller.busy or not bool(self.controller.command.text)
        )
        for button in self.query(MiniAction):
            button.apply_theme(getattr(self.app, "role_colors", DEFAULT))
        self.place()
        error = self.query_one("#assistant-error", Static)
        error.update(self.controller.error)
        error.display = bool(self.controller.error)

    def animate_busy(self):
        if self.controller.busy:
            self.query_one("#assistant-indicator", Static).update(
                self.controller.indicator()
            )

    async def on_mini_action_pressed(self, event):
        event.stop()
        if event.button.id == "assistant-agent":
            self.action_agent()
        elif event.button.id == "assistant-cancel":
            await self.action_cancel()
        elif (
            event.button.id == "assistant-confirm"
            and not self.job
            and self.controller.command.text
        ):
            self.capture()
            self.finish("run")

    def capture(self):
        field = self.query_one(CosmosInput)
        self.controller.input.text = field.value
        self.controller.input.buffer.cursor_position = field.cursor_position

    def on_input_submitted(self, event):
        if not self.job:
            self.capture()
            self.job = asyncio.create_task(self.generate())

    async def generate(self):
        try:
            await self.controller.generate()
        finally:
            self.job = None

    def finish(self, action):
        if not self.finished:
            self.finished = True
            self.dismiss(dict(action=action, state=snapshot(self.controller)))

    async def action_cancel(self):
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
        self.capture()
        self.controller.recall_request(direction)
        self.sync()

    def action_agent(self):
        if not self.job:
            self.capture()
            self.app.agent_prompt = (
                self.controller.command.text or self.controller.input.text
            )
            self.finish("edit")
            self.app.call_after_refresh(self.app.action_leader_key, "g")

    async def on_unmount(self):
        if self.job:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)
