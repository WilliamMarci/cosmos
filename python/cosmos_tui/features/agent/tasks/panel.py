"""Compact task and pane-control management. Only the popup covers the workspace."""

import asyncio
import json
from datetime import datetime

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Label, ListItem, ListView, Static

from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.features.agent.control import ControlStore
from cosmos_tui.features.agent.tasks.storage import Tasks
from cosmos_tui.features.agent.tasks.lifecycle import action
from cosmos_tui.features.agent.tasks import runtime


async def pane_positions(socket):
    from cosmos_tui.features.agent.terminal import TerminalTools

    return {
        row["pane_id"]: f"{row['session_name']} · {row['window_index']}:{row['pane_index']}"
        for row in await TerminalTools(socket).panes()
    }


class TaskPopup(CosmosModal):
    preserve_workspace_graphics = True

    def graphics_covers(self):
        from cosmos_tui.ui.cells import Rect

        return [
            Rect(
                frame.region.x, frame.region.y, frame.region.width, frame.region.height
            )
            for frame in self.query(Frame)
        ]


class TaskPanel(TaskPopup):
    task_context = True

    async def action_task_pause(self):
        await self.perform("pause")

    async def action_task_resume(self):
        await self.perform("resume")

    async def action_task_check(self):
        await self.perform("check")

    async def action_task_more(self):
        await self.perform("more")

    async def action_task_controls(self):
        await self.perform("controls")

    async def action_task_history(self):
        await self.perform("history")

    async def action_task_reschedule(self):
        await self.perform("reschedule")

    async def action_task_mode(self):
        await self.perform("mode")

    async def action_task_permissions(self):
        await self.perform("permissions")

    async def action_task_cancel_task(self):
        await self.perform("cancel")

    async def action_task_interrupt_program(self):
        await self.perform("interrupt_program")

    def action_task_cancel(self):
        self.dismiss(None)

    BINDINGS = [Binding("escape,q", "cancel", show=False)]
    DEFAULT_CSS = """
    TaskPanel { align: center middle; background: transparent; background-tint: transparent; }
    #tasks-frame { width: 86; max-width: 95%; height: 24; max-height: 85%; padding: 0 1; }
    #tasks-list { height: 1fr; background: transparent; }
    #tasks-detail { height: 4; overflow-y: auto; }
    #tasks-buttons { height: 1; }
    #tasks-buttons Button { height: 1; min-width: 7; width: auto; border: none; padding: 0 1; margin: 0 1 0 0; text-style: none; }
    TaskText { align: center middle; }
    #task-text-frame { width: 86; max-width: 95%; height: 20; max-height: 85%; }
    #task-text { height: 1fr; overflow-y: auto; }
    #task-edit { height: 1; border: none; padding: 0; }
    """

    def compose(self):
        with Frame(id="tasks-frame") as frame:
            frame.set_heading("Agent tasks", "workspace.tasks")
            yield ListView(id="tasks-list")
            yield Static(id="tasks-detail")
            with Horizontal(id="tasks-buttons"):
                for key, label in (
                    ("pause", "⏸ Pause"),
                    ("resume", "▶ Resume"),
                    ("check", "Check"),
                    ("controls", "Controls"),
                    ("more", "···"),
                ):
                    yield Button(label, id="task-" + key)

    async def on_mount(self):
        self.store = Tasks(self.app.backend.argv[2])
        self.store.purge_controls()
        self.rows, self.signature, self.loading = [], None, False
        palette = self.app.role_colors
        for button in self.query(Button):
            button.styles.background = palette["base"]
            button.styles.color = palette["accl"]
        await self.reload()
        self.set_interval(0.5, self.reload)
        self.query_one(ListView).focus()

    def selected(self):
        index = self.query_one(ListView).index
        return (
            self.rows[index] if index is not None and index < len(self.rows) else None
        )

    async def reload(self):
        if self.loading:
            return
        self.loading = True
        try:
            rows = self.store.list()
            positions = await pane_positions(self.app.backend.argv[2])
            signature = [(r["id"], r["revision"], r["state"], positions.get(r["pane"])) for r in rows]
            if signature == self.signature:
                return
            selected = self.selected()
            self.rows, self.signature = rows, signature
            listing = self.query_one(ListView)
            old = listing.index or 0
            await listing.clear()
            items = []
            for row in rows:
                text = Text(
                    row["state"].replace("_", " ").ljust(13),
                    style=self.app.role_colors["accl"],
                )
                text.append(
                    f" {positions.get(row['pane'], 'Unavailable terminal')} · {row['goal'][:120]}",
                    style=self.app.role_colors["fg"],
                )
                items.append(ListItem(Label(text)))
            await listing.extend(items)
            listing.index = (
                next(
                    (
                        i
                        for i, r in enumerate(rows)
                        if selected and r["id"] == selected["id"]
                    ),
                    min(old, len(rows) - 1),
                )
                if rows
                else None
            )
            self.detail()
        finally:
            self.loading = False

    def detail(self):
        row = self.selected()
        if not row:
            self.query_one("#tasks-detail", Static).update(
                "No tasks · ask Cosmos Agent to schedule or watch a terminal task"
            )
            return
        due = (
            datetime.fromtimestamp(row["next_run"])
            .astimezone()
            .isoformat(timespec="seconds")
            if row["next_run"]
            else "—"
        )
        text = Text(
            f"{row['goal']}\n{row['mode']} · next {due}\n{row['id']}\n",
            style=self.app.role_colors["fg"],
        )
        text.append(
            json.dumps(row["result"], ensure_ascii=False)
            if row["result"]
            else "Model completion is not task success",
            style=self.app.role_colors["mute"],
        )
        self.query_one("#tasks-detail", Static).update(text)

    def on_list_view_highlighted(self):
        self.detail()

    async def on_button_pressed(self, event):
        event.stop()
        await self.perform(event.button.id.removeprefix("task-"))

    async def controls_menu(self):
        from cosmos_tui.features.navigation.menus import StartMenu

        socket = self.app.backend.argv[2]

        async def entries():
            rows = await asyncio.to_thread(ControlStore(socket).status)
            positions = await pane_positions(socket)
            return [
                dict(
                    label=f"{row['state']} · {positions.get(row['pane'], 'Unavailable terminal')} · {row['task'][:80]}",
                    pane=row["pane"],
                )
                for row in rows
            ] or [dict(label="No pane controls", enabled=False)]

        async def choose(row):
            if not row or "pane" not in row:
                return

            async def confirm():
                return [
                    dict(label="Keep control", operation=None),
                    dict(label="End control · leave program running", operation="end"),
                ]

            async def ended(value):
                if not value:
                    return
                await asyncio.to_thread(ControlStore(socket).change, row["pane"], "cancel")
                await self.app.notification_events.publish(
                    "Agent control ended",
                    source="agent-tasks",
                    level="info",
                )
                await self.reload()

            self.app.push_screen(StartMenu(confirm), ended)

        self.app.push_screen(StartMenu(entries), choose)

    async def perform(self, operation):
        if operation == "controls":
            await self.controls_menu()
            return
        row = self.selected()
        if not row:
            return
        if operation == "more":
            from cosmos_tui.features.navigation.menus import StartMenu

            async def entries():
                entries = [
                    dict(label=label, operation=op)
                    for op, label in (
                        ("history", "Run history"),
                        ("permissions", "Pending permissions"),
                        ("mode", "Wake mode · " + row["mode"]),
                        ("reschedule", "Reschedule"),
                        ("cancel", "Cancel task · leave program running"),
                        ("interrupt_program", "Interrupt program · sends Ctrl+C"),
                    )
                ]
                if row["state"] in ("cancelled", "succeeded", "failed"):
                    entries.append(dict(label="Delete task", operation="delete"))
                return entries

            async def choose(entry):
                if entry:
                    await self.operate(row, entry["operation"])

            self.app.push_screen(StartMenu(entries), choose)
            return
        await self.operate(row, operation)

    async def operate(self, row, operation):
        socket = self.app.backend.argv[2]
        try:
            if operation == "history":
                self.app.push_screen(
                    TaskText(
                        "Task history",
                        json.dumps(
                            self.store.history(row["id"]), ensure_ascii=False, indent=2
                        ),
                    )
                )
            elif operation == "reschedule":

                async def save(value):
                    if value:
                        try:
                            await action(
                                socket,
                                row["id"],
                                "reschedule",
                                schedule=json.loads(value),
                            )
                            await self.reload()
                        except (OSError, RuntimeError, ValueError) as error:
                            await self.app.action_error("task.reschedule", error)

                self.app.push_screen(
                    TaskText(
                        "Reschedule · JSON",
                        'Examples: {"after_seconds":60}, {"interval_seconds":300},\n{"daily":"09:00","timezone":"Europe/Zurich"}',
                        edit=True,
                    ),
                    save,
                )
            elif operation in ("cancel", "interrupt_program", "delete"):
                from cosmos_tui.features.navigation.menus import StartMenu

                async def confirm():
                    return [
                        dict(label="Cancel", operation=None),
                        dict(
                            label="Confirm " + operation.replace("_", " "),
                            operation=operation,
                        ),
                    ]

                async def confirmed(value):
                    if value and value["operation"]:
                        await self.apply(row, value["operation"])

                self.app.push_screen(StartMenu(confirm), confirmed)
            elif operation == "permissions":
                descriptor = await runtime.find(
                    socket, row["conversation"], row["runtime"]
                )
                if not descriptor:
                    raise RuntimeError("Agent runtime is unavailable")
                pending = (
                    await runtime.call(descriptor, "status", row["conversation"])
                ).get("permissions", [])
                from cosmos_tui.features.navigation.menus import StartMenu

                async def entries():
                    return [
                        dict(
                            label=f"{decision.title()} · {p.get('action', 'tool')} · {str(p.get('resources', ''))[:160]}",
                            request=p["id"],
                            decision=decision,
                        )
                        for p in pending
                        for decision in ("once", "reject")
                    ] or [dict(label="No pending permissions", enabled=False)]

                async def reply(value):
                    if value and "request" in value:
                        try:
                            result = await runtime.call(
                                descriptor,
                                "permission",
                                row["conversation"],
                                request_id=value["request"],
                                decision=value["decision"],
                            )
                            if result.get("stale"):
                                await self.app.notification_events.publish(
                                    result["message"],
                                    source="agent-tasks",
                                    level="warning",
                                )
                        except (OSError, RuntimeError, ValueError) as error:
                            await self.app.action_error("task.permission", error)

                self.app.push_screen(StartMenu(entries), reply)
            else:
                await self.apply(row, operation)
        except (OSError, RuntimeError, ValueError) as error:
            await self.app.action_error("tasks." + operation, error)

    async def apply(self, row, operation):
        if operation == "delete":
            self.store.delete(row["id"])
        else:
            await action(self.app.backend.argv[2], row["id"], operation)
            if operation == "cancel":
                self.store.delete(row["id"])
        await self.reload()

    def action_cancel(self):
        self.dismiss(None)


class TaskText(TaskPopup):
    DEFAULT_CSS = """
    TaskText { align: center middle; background: transparent; background-tint: transparent; }
    #task-text-frame { width: 86; max-width: 95%; height: 20; max-height: 85%; }
    #task-text { height: 1fr; overflow-y: auto; }
    #task-edit { height: 1; border: none; padding: 0; }
    """
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, title, text, edit=False):
        super().__init__()
        self.title_text, self.text, self.edit = title, text, edit

    def compose(self):
        with Frame(id="task-text-frame") as frame:
            frame.set_heading(self.title_text)
            with VerticalScroll(id="task-text"):
                yield Static(Text(self.text))
            if self.edit:
                yield CosmosInput(
                    placeholder="Schedule JSON · Enter to save", id="task-edit"
                )

    def on_mount(self):
        if self.edit:
            self.query_one(CosmosInput).focus()
        else:
            self.query_one(VerticalScroll).focus()

    def on_input_submitted(self, event):
        self.dismiss(event.value)

    def action_cancel(self):
        self.dismiss(None)
