"""Deterministic differences and real detached watch completion without a model."""

import asyncio
import os
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

from cosmos_tui.features.agent.monitor.detector import Detector, baseline
from cosmos_tui.features.agent.monitor.storage import Watches
from cosmos_tui.features.agent.terminal import TerminalTools


def screen(text):
    return dict(
        text=text,
        pid="1",
        window_id="@0",
        pane_width=80,
        pane_height=24,
        pane_current_command="bash",
    )


class TextPredicateTests(unittest.TestCase):
    def test_regex_flags_alternatives_absence_and_literal_compatibility(self):
        from cosmos_tui.features.agent.monitor.predicates import text_matches

        output = "progress\nInstallation COMPLETE\n"
        pattern = r"(?im)^(successful installation|installation complete)$"
        self.assertTrue(text_matches("regex_present", pattern, output))
        self.assertFalse(text_matches("regex_absent", pattern, output))
        self.assertTrue(text_matches("regex_absent", "error|failed", output))
        self.assertFalse(text_matches("text_present", "COMPLETE|failed", output))
        self.assertTrue(text_matches("text_present", "Installation COMPLETE", output))

    def test_invalid_and_expensive_patterns(self):
        from cosmos_tui.features.agent.monitor.predicates import (
            text_matches, validate_pattern,
        )

        with self.assertRaisesRegex(ValueError, "Invalid watch regex"):
            validate_pattern("regex_present", "[")
        for condition in ("regex_present", "regex_absent"):
            with self.assertRaises(TimeoutError):
                text_matches(condition, r"(a+)+$", "a" * 20000 + "!")


class DetectorTests(unittest.TestCase):
    def test_local_animation_is_not_completion(self):
        detector = Detector(baseline(screen("A\nbody")))
        self.assertIsNone(detector.update(screen("B\nbody"), 0))
        self.assertIsNone(detector.update(screen("A\nbody"), 0.2))
        event = detector.update(screen("B\nbody"), 0.4)
        self.assertEqual(event["type"], "animation")
        self.assertEqual(event["rows"], [])
        detector.update(screen("A\nresult"), 0.6)
        event = detector.update(screen("B\nresult"), 1.0)
        self.assertEqual(event["type"], "changed")
        self.assertEqual(event["rows"], [2])

    def test_geometry_invalidates(self):
        detector = Detector(baseline(screen("body")))
        changed = screen("body")
        changed["pane_height"] = 23
        self.assertEqual(detector.update(changed, 0)["type"], "invalidated")


@unittest.skipUnless(shutil.which("tmux"), "requires tmux")
class DetachedMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_conditions_timeout_cancel_and_duplicate_suppression(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                XDG_RUNTIME_DIR=directory,
                XDG_CONFIG_HOME=directory + "/config",
                COSMOS_CONTROL_SOCKET=directory + "/absent.sock",
            ),
        ):
            socket = "cosmos-watch-" + uuid.uuid4().hex
            tools = TerminalTools(socket)
            try:
                await tools.backend.cli(
                    "-f",
                    "/dev/null",
                    "new-session",
                    "-d",
                    "-s",
                    "fixture",
                    "env PS1='MONITOR_READY> ' bash --noprofile --norc",
                )
                pane = (await tools.panes())[0]["pane_id"]
                for _ in range(40):
                    ready = await tools.read_screen(pane, wait_ms=50)
                    if "MONITOR_READY" in ready["text"]:
                        break
                self.assertIn("MONITOR_READY", ready["text"])
                snapshot = await tools.observe(pane)
                lease = await tools.acquire_control(
                    pane, snapshot["snapshot_id"], "Watch fixture"
                )
                # A prior CLI stop must not disable newly registered watches.
                Watches(socket).path.with_suffix(".suspended").touch()
                first = await tools.watch_terminal(
                    pane,
                    "text_present",
                    "WATCH_OUTPUT",
                    8,
                    control_token=lease["token"],
                )
                regex_watch = await tools.watch_terminal(
                    pane, "regex_present", r"(?i)watch_outp.t", 8
                )
                with self.assertRaisesRegex(ValueError, "Invalid watch regex"):
                    await tools.watch_terminal(pane, "regex_present", "[", 8)
                second = await tools.watch_terminal(
                    pane, "text_present", "NEVER_EMITTED", 1
                )
                cancelled = await tools.watch_terminal(
                    pane, "changed", timeout_seconds=8
                )
                await tools.cancel_terminal_watch(cancelled["id"])
                await tools.send_text(pane, "printf 'WATCH_%s' OUTPUT")
                await tools.send_keys(pane, ["Enter"])
                for _ in range(80):
                    rows = {row["id"]: row for row in await tools.terminal_watches()}
                    if (
                        rows[first["id"]]["state"] == "matched"
                        and rows[second["id"]]["state"] == "timed_out"
                        and rows[regex_watch["id"]]["state"] == "matched"
                    ):
                        break
                    await asyncio.sleep(0.1)
                self.assertEqual(rows[first["id"]]["state"], "matched")
                self.assertEqual(rows[regex_watch["id"]]["state"], "matched")
                self.assertFalse(rows[first["id"]]["result"]["model_woken"])
                self.assertFalse(rows[first["id"]]["result"]["task_complete"])
                self.assertEqual(rows[second["id"]]["state"], "timed_out")
                self.assertEqual(rows[cancelled["id"]]["state"], "cancelled")
                from cosmos_tui.features.agent.control import ControlStore

                controls = ControlStore(socket)
                row = await tools.pane(pane)
                controls.acquire(pane, "manual-fixture", "Paused task", row["pid"])
                controls.change(pane, "pause")
                paused = await tools.watch_terminal(
                    pane, "text_present", "MANUAL_OUTPUT", 8
                )
                await tools.backend.cli(
                    "send-keys", "-t", pane, "printf 'MANUAL_%s' OUTPUT", "Enter"
                )
                for _ in range(80):
                    paused_row = next(
                        r
                        for r in await tools.terminal_watches()
                        if r["id"] == paused["id"]
                    )
                    if paused_row["state"] != "waiting":
                        break
                    await asyncio.sleep(0.1)
                self.assertEqual(paused_row["state"], "matched")
                self.assertEqual(controls.status()[0]["state"], "paused")
                controls.change(pane, "cancel")
                store = Watches(socket)
                self.assertFalse(store.finish(first["id"], "matched", {}))
                self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(
                    (await tools.pane(pane))["pane_current_command"], "bash"
                )
            finally:
                await tools.backend.cli("kill-server")
