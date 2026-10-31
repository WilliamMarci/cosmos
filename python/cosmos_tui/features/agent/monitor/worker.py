"""Detached, single-owner local terminal monitor. Never invokes a model."""

import asyncio
import fcntl
import os
import sys
import time

from cosmos_tui.features.agent.monitor.detector import Detector
from cosmos_tui.features.agent.monitor.storage import Watches
from cosmos_tui.features.agent.monitor.service import starting
from cosmos_tui.features.agent.terminal import TerminalTools
from cosmos_tui.core.services import NotificationEvents


async def run(socket):
    watches = Watches(socket)
    lock = os.open(
        str(watches.path) + ".worker", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        tools, detectors = TerminalTools(socket), {}
        while True:
            with starting(watches):
                if watches.path.with_suffix(".suspended").exists():
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    return
            pending = watches.list(pending=True)
            if not pending:
                with starting(watches):
                    if not watches.list(pending=True):
                        fcntl.flock(lock, fcntl.LOCK_UN)
                        return
                continue
            screens = {}
            for watch in pending:
                pane = watch["pane"]
                if pane not in screens:
                    try:
                        screen = await tools.read_screen(pane)
                        if screen["truncated"]:
                            raise ValueError("Terminal capture was truncated")
                        screens[pane] = screen
                    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                        screens[pane] = dict(error=str(error))
                screen = screens[pane]
                state, evidence = None, None
                if "error" in screen:
                    state, evidence = (
                        "invalidated",
                        dict(type="target_unavailable", reason=screen["error"]),
                    )
                else:
                    detector = detectors.setdefault(
                        watch["id"], Detector(watch["baseline"])
                    )
                    event = detector.update(screen, time.monotonic())
                    if event and event["type"] == "invalidated":
                        state, evidence = "invalidated", event
                    elif watch["kind"] in ("text_present", "text_absent") and (
                        (watch["needle"] in screen["text"])
                        == (watch["kind"] == "text_present")
                    ):
                        state, evidence = (
                            "matched",
                            dict(
                                type=watch["kind"],
                                source="terminal_text",
                                condition_met=True,
                            ),
                        )
                    elif (
                        watch["kind"] == "changed"
                        and event
                        and event["type"] == "changed"
                    ):
                        state, evidence = "matched", event
                    elif (
                        watch["kind"] == "program_changed"
                        and screen["pane_current_command"]
                        != watch["baseline"]["program"]
                    ):
                        state, evidence = (
                            "matched",
                            dict(
                                type="program_changed",
                                program=screen["pane_current_command"],
                            ),
                        )
                if state is None and time.time() >= watch["deadline"]:
                    state, evidence = (
                        "timed_out",
                        dict(type="timeout", condition_met=False),
                    )
                if state and watches.finish(
                    watch["id"],
                    state,
                    dict(evidence, task_complete=False, model_woken=False),
                ):
                    detectors.pop(watch["id"], None)
                    try:
                        await NotificationEvents().publish(
                            f"Terminal watch {state} · {pane} · {watch['id'][-6:]}",
                            source="agent-monitor",
                            level="warning" if state != "matched" else "info",
                            session_id=watch["baseline"].get("session_id"),
                        )
                    except (OSError, ValueError, RuntimeError, TimeoutError):
                        pass
            active = {w["id"] for w in pending}
            detectors = {k: v for k, v in detectors.items() if k in active}
            await asyncio.sleep(0.2)
    finally:
        os.close(lock)


if __name__ == "__main__":
    from cosmos_tui.core.diagnostics import configure
    from cosmos_tui.features.agent.control import location
    import logging

    os.umask(0o077)
    configure(path=location(sys.argv[1]).with_suffix(".monitor.log"))
    try:
        asyncio.run(run(sys.argv[1]))
    except Exception:
        logging.getLogger(__name__).exception("Terminal monitor stopped unexpectedly")
        raise
