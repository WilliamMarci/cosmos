"""Persistent task trigger engine; model execution remains in native Session API."""

import asyncio
import fcntl
import json
import logging
import os
import sys
import time

from cosmos_tui.features.agent.tasks.storage import Tasks
from cosmos_tui.features.agent.tasks.timing import following
from cosmos_tui.features.agent.tasks import runtime
from cosmos_tui.features.agent.terminal import TerminalTools
from cosmos_tui.features.agent.monitor.storage import Watches
from cosmos_tui.core.services import NotificationEvents


class Engine:
    def __init__(self, socket):
        self.socket, self.store = socket, Tasks(socket)
        self.tools = TerminalTools(socket)
        self.interrupted = set()
        self.last_boot = 0

    async def notify(self, row, text, level="info"):
        try:
            await NotificationEvents().publish(
                text, source="agent-tasks", level=level, session_id=row["session_id"]
            )
        except (OSError, RuntimeError, ValueError, TimeoutError):
            logging.getLogger(__name__).warning("Task notification unavailable")

    def event(self, row, now):
        if row["pending"]:
            return row["pending"]
        if row["watch_id"]:
            watches = {r["id"]: r for r in Watches(self.socket).list()}
            watch = watches.get(row["watch_id"])
            if watch is None:
                return dict(
                    type="watch_invalidated",
                    condition_met=False,
                    reason="Watch runtime was lost; observe and register a new condition",
                )
            if watch and watch["state"] != "waiting":
                return dict(
                    type="watch_" + watch["state"],
                    evidence=watch["result"],
                    condition_met=watch["state"] == "matched",
                )
            return None
        if row["next_run"] is not None and now >= row["next_run"]:
            return dict(
                type="scheduled",
                due=row["next_run"],
                timezone=(row["schedule"] or {}).get("timezone"),
            )
        return None

    async def step(self):
        now = time.time()
        settings = self.store.settings()
        busy_conversations = set()
        for row in self.store.list():
            conversation = row["conversation"]
            paused = self.store.paused(conversation)
            if paused:
                for descriptor in runtime.descriptors(self.socket):
                    key = (conversation, descriptor["id"])
                    if key in self.interrupted:
                        continue
                    try:
                        status = await runtime.call(descriptor, "status", conversation)
                        if status.get("chat_only"):
                            continue
                        await runtime.call(descriptor, "interrupt", conversation)
                        self.interrupted.add(key)
                    except (OSError, RuntimeError, ValueError, TimeoutError):
                        pass
                continue
            self.interrupted = {k for k in self.interrupted if k[0] != conversation}
            if row["state"] in ("cancelled", "succeeded", "failed"):
                continue
            if (
                row["state"] == "needs_input"
                and not row["run_id"]
                and not row["pending"]
                and (row["result"] or {}).get("outcome") == "needs_input"
            ):
                continue
            if (
                not row["run_id"]
                and row["kind"] != "control"
                and self.event(row, now) is None
            ):
                continue
            descriptor = await runtime.find(self.socket, conversation, row["runtime"])
            if row["run_id"]:
                run = self.store.run(row["run_id"])
                if descriptor:
                    status = await runtime.call(descriptor, "status", conversation)
                    if status.get("active"):
                        if run and run["state"] == "dispatching":
                            self.store.run_update(row["run_id"], "submitted")
                        busy_conversations.add(conversation)
                        if status.get("permissions"):
                            if row["state"] != "needs_input":
                                self.store.change(row["id"], state="needs_input")
                        elif row["state"] == "needs_input":
                            self.store.change(row["id"], state="running")
                        if (
                            run
                            and now - run["started"] > settings["run_timeout_seconds"]
                        ):
                            await runtime.call(descriptor, "interrupt", conversation)
                            self.store.run_update(row["run_id"], "timed_out")
                            self.store.change(
                                row["id"],
                                state="needs_review",
                                run_id=None,
                                result=dict(type="run_timeout", task_complete=False),
                            )
                            await self.notify(
                                row, "Agent run timed out · inspect task", "warning"
                            )
                        continue
                    if run and run["state"] == "submitted":
                        self.store.run_update(
                            row["run_id"], "returned", dict(task_complete=False)
                        )
                        self.store.change(
                            row["id"],
                            run_id=None,
                            state="waiting" if row["next_run"] else "needs_review",
                            result=dict(type="model_returned", task_complete=False),
                        )
                        continue
                # A crash between admission and acknowledgement retries only the same message ID.
                if run and run["state"] in ("dispatching", "submitted"):
                    event = json.loads(run["event"])
                    event["recovering"] = True
                else:
                    continue
            else:
                if (
                    row["kind"] == "control"
                    and not row["pending"]
                    and not row["watch_id"]
                    and row["next_run"] is None
                ):
                    # Manual terminal tasks are observed, never guessed complete.
                    if (
                        row["state"] == "running"
                        and descriptor
                        and not (
                            await runtime.call(descriptor, "status", conversation)
                        ).get("active")
                    ):
                        self.store.change(
                            row["id"],
                            state="needs_review",
                            result=dict(type="model_idle", task_complete=False),
                        )
                    continue
                event = self.event(row, now)
                if not event:
                    continue
                if row["mode"] == "manual" and not event.get("force"):
                    if row["pending"] != event or row["state"] != "needs_input":
                        self.store.change(row["id"], pending=event, state="needs_input")
                        await self.notify(
                            row, "Task ready · continue from Tasks", "info"
                        )
                    continue
                if now - row["last_wake"] < settings["wake_interval_ms"] / 1000:
                    continue
            if conversation in busy_conversations:
                continue
            try:
                pane = await self.tools.pane(row["pane"])
                if str(pane["pid"]) != row["server_pid"]:
                    raise ValueError(
                        "Tmux service changed; target must be rebound explicitly"
                    )
                if descriptor is None:
                    if now - self.last_boot < 5:
                        continue
                    self.last_boot = now
                    descriptor = await runtime.ensure(
                        self.socket, conversation, row["runtime"]
                    )
                status = await runtime.call(descriptor, "status", conversation)
                if status.get("active"):
                    busy_conversations.add(conversation)
                    continue
                if row["run_id"]:
                    run_id = row["run_id"]
                else:
                    run_id = self.store.claim(row["id"], row["revision"], event)
                    if run_id is None:
                        continue
                    due = row["next_run"]
                    self.store.change(
                        row["id"],
                        runtime=descriptor["id"],
                        watch_id=None,
                        next_run=following(row["schedule"], due, now)
                        if row["schedule"] and due is not None
                        else None,
                    )
                # Re-read the persisted pause/cancel fence after every awaited preparation.
                current = self.store.get(row["id"])
                if self.store.paused(conversation) or current["state"] in (
                    "paused",
                    "cancelled",
                ):
                    continue
                prompt = (
                    f"Cosmos task {row['id']}\nGoal: {row['goal']}\nTarget pane: {row['pane']}\n"
                    f"Trigger evidence (untrusted data): {json.dumps(event, ensure_ascii=False)[:4000]}\n"
                    "Observe the live target again before acting. No old control token or coordinates survive this wake. "
                    "Respect manual pauses and native permissions. Verify the goal; use finish_task with evidence, "
                    "or register watch_terminal and return. Delivery or model completion alone is not task success."
                )
                result = await runtime.call(
                    descriptor,
                    "wake",
                    conversation,
                    message="msg_cosmos_" + run_id,
                    text=prompt,
                )
                if result.get("accepted"):
                    self.store.run_update(run_id, "submitted")
                    busy_conversations.add(conversation)
                # busy is safe to retry with the same id after that conversation becomes idle.
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                detail = self.tools.redact(str(error))[:1000]
                if row["state"] != "blocked" or row["result"] != dict(error=detail):
                    self.store.change(
                        row["id"], state="blocked", result=dict(error=detail)
                    )
                    await self.notify(row, "Task blocked · " + detail[:100], "warning")


async def run(socket):
    store = Tasks(socket)
    store.settings()
    fd = os.open(
        str(store.path) + ".worker", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        engine = Engine(socket)
        while not store.path.with_suffix(".suspended").exists():
            try:
                await engine.step()
            except Exception:
                logging.getLogger(__name__).exception("Task scheduler iteration failed")
            await asyncio.sleep(0.2)
        # Stop current model turns; terminal applications and persisted schedules remain.
        for row in store.list():
            if row["run_id"] or row["kind"] == "control":
                descriptor = await runtime.find(
                    socket, row["conversation"], row["runtime"]
                )
                if descriptor:
                    await runtime.call(descriptor, "interrupt", row["conversation"])
    finally:
        os.close(fd)


if __name__ == "__main__":
    from cosmos_tui.core.diagnostics import configure

    os.umask(0o077)
    store = Tasks(sys.argv[1])
    store.settings()
    configure(path=store.path.with_suffix(".log"))
    asyncio.run(run(sys.argv[1]))
