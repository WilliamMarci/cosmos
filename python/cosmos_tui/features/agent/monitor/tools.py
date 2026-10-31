"""Bounded terminal-watch tools. Registration returns instead of model sleep loops."""

import asyncio

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
            "changed",
            "program_changed",
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
            or condition.startswith("text_")
            and not text
        ):
            raise ValueError(
                "Text conditions need a nonempty string of at most 256 characters"
            )
        if self.redact(text) != text:
            raise ValueError("Do not register credentials as watch text")
        await self.pane(pane)
        if control_token is not None:
            await self.release_control(pane, control_token)
        screen = await self.read_screen(pane)
        if screen["truncated"]:
            raise ValueError(
                "Terminal capture truncated; cannot establish a watch baseline"
            )
        socket = self.backend.argv[2]
        watches = Watches(socket)

        def register():
            with starting(watches):
                identity = watches.create(
                    pane, condition, text, timeout_seconds, baseline(screen)
                )
                start(watches, socket)
                return identity

        identity = await asyncio.to_thread(register)
        return dict(
            id=identity,
            pane=pane,
            state="waiting",
            model_wakeup_available=False,
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
