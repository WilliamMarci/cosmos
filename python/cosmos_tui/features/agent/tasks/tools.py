"""Model-facing scheduling APIs; trusted conversation identity is never an argument."""

import asyncio

from cosmos_tui.features.agent.tasks.storage import Tasks
from cosmos_tui.features.agent.tasks.timing import normalize
from cosmos_tui.features.agent.tasks import service


class TaskTools:
    def task_owner(self):
        if not getattr(self, "conversation", None):
            raise ValueError("Task tools require the native authenticated Cosmos Agent")
        store = Tasks(self.backend.argv[2])
        return store

    async def schedule_task(
        self, pane, goal, schedule, mode="auto", control_token=None
    ):
        store = self.task_owner()
        if store.paused(self.conversation):
            raise ValueError("Conversation paused; only the user may resume it")
        if self.redact(goal) != goal:
            raise ValueError("Do not put credentials in task goals")
        spec, due = normalize(schedule)
        target = await self.pane(pane)
        token = control_token or self.control_tokens.get(pane)
        if token:
            await self.release_control(pane, token)
        row = await asyncio.to_thread(
            store.create,
            self.conversation,
            self.runtime_id,
            target,
            goal,
            schedule=spec,
            next_run=due,
            mode=mode,
        )
        await asyncio.to_thread(service.start, self.backend.argv[2])
        return dict(task=row, model_wakeup_available=True, task_complete=False)

    async def list_tasks(self):
        store = self.task_owner()
        rows = [
            r
            for r in await asyncio.to_thread(store.list)
            if r["conversation"] == self.conversation
        ]
        for row in rows:
            row.pop("runtime", None)
        return rows

    async def task_history(self, id):
        store = self.task_owner()
        if store.get(id)["conversation"] != self.conversation:
            raise PermissionError("Task belongs to a different conversation")
        return await asyncio.to_thread(store.history, id)

    async def finish_task(self, id, outcome, summary):
        store = self.task_owner()
        row = store.get(id)
        if row["conversation"] != self.conversation:
            raise PermissionError("Task belongs to a different conversation")
        if row["state"] in ("cancelled", "paused") or store.paused(self.conversation):
            raise ValueError("A cancelled/paused task cannot be completed by the Agent")
        if (
            outcome not in ("succeeded", "failed", "needs_input")
            or not isinstance(summary, str)
            or not 1 <= len(summary) <= 2000
        ):
            raise ValueError(
                "outcome must be succeeded/failed/needs_input with a 1–2000 character evidence summary"
            )
        for pane, token in list(self.control_tokens.items()):
            await self.release_control(pane, token)
        return await asyncio.to_thread(
            store.finish, id, self.conversation, outcome, self.redact(summary)
        )
