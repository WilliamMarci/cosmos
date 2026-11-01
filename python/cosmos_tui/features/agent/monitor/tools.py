"""Bounded terminal-watch tools. Registration returns instead of model sleep loops."""

import asyncio

from cosmos_tui.features.agent.monitor.predicates import TEXT_CONDITIONS, validate_pattern

from cosmos_tui.features.agent.monitor.detector import baseline
from cosmos_tui.features.agent.monitor.storage import Watches
from cosmos_tui.features.agent.monitor.service import starting, start


class TerminalWatches:
    async def watch_terminal(
        self, pane, condition, text="", timeout_seconds=300, control_token=None
    ):
        if condition not in (
            "text_present",
            "text_absent",
            "regex_present",
            "regex_absent",
            "changed",
            "program_changed",
            "bash_prompt",
        ):
            raise ValueError("Unsupported terminal watch condition")
        if (
            type(timeout_seconds) not in (int, float)
            or not 1 <= timeout_seconds <= 86400
        ):
            raise ValueError("timeout_seconds must be between 1 and 86400")
        if (
            not isinstance(text, str)
            or len(text) > 256
            or condition in TEXT_CONDITIONS
            and not text
        ):
            raise ValueError(
                "Text conditions need a nonempty string of at most 256 characters"
            )
        validate_pattern(condition, text)
        if self.redact(text) != text:
            raise ValueError("Do not register credentials as watch text")
        await self.pane(pane)
        if getattr(self, "conversation", None):
            from cosmos_tui.features.agent.tasks.storage import Tasks

            if Tasks(self.backend.argv[2]).paused(self.conversation):
                raise ValueError("Conversation paused; user resume required")
            control_token = control_token or self.control_tokens.get(pane)
        if control_token is not None:
            await self.release_control(pane, control_token)
        screen = await self.read_screen(pane)
        if screen["truncated"]:
            raise ValueError(
                "Terminal capture truncated; cannot establish a watch baseline"
            )
        initial = baseline(screen)
        if condition == "bash_prompt":
            from cosmos_tui.features.agent.monitor.bash import prompt_stamp

            initial["bash_prompt"] = await prompt_stamp(self, pane)
            if initial["bash_prompt"] is None:
                raise ValueError(
                    "Bash prompt adapter unavailable; source cosmosrc or use a text condition"
                )
        socket = self.backend.argv[2]
        watches = Watches(socket)

        def register():
            with starting(watches):
                identity = watches.create(
                    pane, condition, text, timeout_seconds, initial
                )
                start(watches, socket)
                return identity

        identity = await asyncio.to_thread(register)
        logical_task = None
        if getattr(self, "conversation", None):
            from cosmos_tui.features.agent.tasks.storage import Tasks
            from cosmos_tui.features.agent.tasks.service import start as start_scheduler

            store = Tasks(socket)
            current = next(
                (
                    r
                    for r in store.list()
                    if r["conversation"] == self.conversation
                    and r["state"] == "running"
                ),
                None,
            )
            if current:
                if current["run_id"]:
                    store.run_update(current["run_id"], "waiting", dict(watch=identity))
                logical_task = store.change(
                    current["id"],
                    watch_id=identity,
                    run_id=None,
                    pending=None,
                    state="waiting",
                )["id"]
            else:
                logical_task = store.create(
                    self.conversation,
                    self.runtime_id,
                    await self.pane(pane),
                    f"Continue after {condition}: {text[:120]}",
                    kind="watch",
                    watch_id=identity,
                )["id"]
            await asyncio.to_thread(start_scheduler, socket)
        return dict(
            task_id=logical_task,
            id=identity,
            pane=pane,
            state="waiting",
            model_wakeup_available=logical_task is not None,
            task_complete=False,
        )

    async def terminal_watches(self):
        rows = await asyncio.to_thread(Watches(self.backend.argv[2]).list)
        for row in rows:
            row.pop("baseline", None)
            row.pop("needle", None)
        return rows

    async def cancel_terminal_watch(self, id):
        cancelled = await asyncio.to_thread(
            Watches(self.backend.argv[2]).finish,
            id,
            "cancelled",
            dict(task_complete=False, reason="Cancelled by request"),
        )
        return dict(id=id, cancelled=cancelled, terminal_interrupted=False)
