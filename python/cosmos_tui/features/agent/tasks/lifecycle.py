"""Control/user task transitions. Cancellation never sends Ctrl+C to the program."""

import asyncio

from cosmos_tui.features.agent.tasks.storage import Tasks
from cosmos_tui.features.agent.tasks import runtime


def control_task(socket, tools, pane, label):
    if not getattr(tools, "conversation", None):
        return None
    store = Tasks(socket)
    for row in store.list():
        if row["conversation"] == tools.conversation and (
            row["state"] == "running"
            or (
                row["kind"] == "control"
                and row["goal"] == label
                and row["state"] in ("waiting", "needs_review", "blocked")
            )
        ):
            store.change(row["id"], state="running", pending=None)
            return row["id"]
    return store.create(
        tools.conversation, tools.runtime_id, pane, label, kind="control"
    )["id"]


def control_changed(socket, conversation, action):
    if not conversation:
        return
    store = Tasks(socket)
    if action in ("pause", "cancel"):
        store.pause(conversation, "cancelled" if action == "cancel" else "manual")
        if action == "cancel":
            for row in store.list():
                if row["conversation"] == conversation and row["state"] == "paused":
                    store.change(
                        row["id"], state="cancelled", pending=None, next_run=None
                    )
        import threading

        def interrupt():
            async def send():
                for descriptor in runtime.descriptors(socket):
                    try:
                        await runtime.call(descriptor, "interrupt", conversation)
                    except (OSError, RuntimeError, ValueError, TimeoutError):
                        pass

            asyncio.run(send())

        threading.Thread(target=interrupt, daemon=True).start()
    elif action == "resume":
        store.resume(conversation)
    from cosmos_tui.features.agent.tasks.service import start

    start(socket)


async def action(socket, identity, operation, *, schedule=None):
    store = Tasks(socket)
    row = store.get(identity)
    if row["state"] in ("cancelled", "succeeded", "failed") and operation in (
        "resume",
        "check",
        "reschedule",
    ):
        raise ValueError("Task has ended; create a new task")
    from cosmos_tui.features.agent.control import ControlStore

    controls = ControlStore(socket)
    if operation in ("pause", "cancel"):
        store.pause(
            row["conversation"], "cancelled" if operation == "cancel" else "manual"
        )
        with controls.locked(write=False) as state:
            panes = [
                p
                for p, c in state.items()
                if c.get("conversation") == row["conversation"]
            ]
        for pane in panes:
            await asyncio.to_thread(
                controls.change, pane, "pause" if operation == "pause" else "cancel"
            )
        if operation == "cancel":
            store.change(identity, state="cancelled", pending=None, next_run=None)
        for descriptor in runtime.descriptors(socket):
            try:
                await runtime.call(descriptor, "interrupt", row["conversation"])
            except (OSError, RuntimeError, ValueError, TimeoutError):
                pass
    elif operation == "resume":
        with controls.locked(write=False) as state:
            panes = [
                p
                for p, c in state.items()
                if c.get("conversation") == row["conversation"]
            ]
        for pane in panes:
            await asyncio.to_thread(controls.change, pane, "resume")
        store.resume(row["conversation"])
    elif operation == "check":
        if row["state"] != "paused":
            store.change(
                identity, state="waiting", pending=dict(type="user_check", force=True)
            )
    elif operation == "mode":
        store.change(identity, mode="manual" if row["mode"] == "auto" else "auto")
    elif operation == "reschedule":
        from cosmos_tui.features.agent.tasks.timing import normalize

        spec, due = normalize(schedule)
        store.change(
            identity,
            schedule=spec,
            next_run=due,
            watch_id=None,
            pending=None,
            state="paused" if store.paused(row["conversation"]) else "waiting",
        )
    elif operation == "interrupt_program":
        # This is a distinct, explicit user action, never part of cancel/pause.
        from cosmos_tui.features.agent.terminal import TerminalTools

        tools = TerminalTools(socket)
        await tools.pane(row["pane"])
        await action(socket, identity, "cancel")
        await tools.backend.cli("send-keys", "-t", row["pane"], "C-c")
    else:
        raise ValueError("Unknown task action")
    from cosmos_tui.features.agent.tasks.service import start

    start(socket)
    return store.get(identity)


def pause_target(socket, pane):
    """Manual input also pauses waiting tasks whose input lease was released."""
    store = Tasks(socket)
    if not store.path.exists():
        return False
    conversations = {
        r["conversation"]
        for r in store.list()
        if r["pane"] == pane
        and r["state"] not in ("paused", "cancelled", "succeeded", "failed")
    }
    for conversation in conversations:
        control_changed(socket, conversation, "pause")
    return bool(conversations)
