"""Task persistence, trigger fences, DST and actual popup/animation regressions."""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from cosmos_tui.features.agent.tasks.storage import Tasks
from cosmos_tui.features.agent.tasks.timing import normalize, following, wall_time
from cosmos_tui.features.agent.tasks.worker import Engine
from cosmos_tui.features.agent.tasks.panel import TaskPanel, TaskText
from cosmos_tui.features.agent.header_ui import HeaderController, header_text
from test_navigation import Probe
from textual.widgets import ListView

PANE = dict(pane_id="%4", pid=1234, session_id="$1")


class Fixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            COSMOS_TASKS_HOME=self.temp.name + "/tasks",
            XDG_RUNTIME_DIR=self.temp.name + "/run",
        )
        self.env.start()
        self.store = Tasks("fixture")
        self.service = patch("cosmos_tui.features.agent.tasks.service.start")
        self.service.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.env.stop)
        self.addCleanup(self.service.stop)

    def task(self, **values):
        return self.store.create(
            "ses_fixture", "runtime", PANE, "Verify result", **values
        )


class StorageTests(Fixture, unittest.TestCase):
    def test_pause_survives_restart_and_claim_is_serialized(self):
        first, second = self.task(), self.task()
        run = self.store.claim(first["id"], first["revision"], dict(type="scheduled"))
        self.assertIsNotNone(run)
        self.assertIsNone(self.store.claim(second["id"], second["revision"], {}))
        self.store.pause("ses_fixture")
        reopened = Tasks("fixture")
        self.assertTrue(reopened.paused("ses_fixture"))
        self.assertEqual(reopened.get(first["id"])["state"], "paused")
        self.assertIsNone(
            reopened.claim(second["id"], reopened.get(second["id"])["revision"], {})
        )
        reopened.resume("ses_fixture")
        self.assertFalse(reopened.paused("ses_fixture"))
        self.assertTrue(reopened.get(first["id"])["pending"]["force"])
        self.assertEqual(reopened.path.stat().st_mode & 0o777, 0o600)

    def test_finish_cannot_overwrite_pause_and_recurring_finish_waits(self):
        row = self.task(schedule=dict(interval_seconds=60), next_run=12345)
        self.store.pause("ses_fixture")
        with self.assertRaises(ValueError):
            self.store.finish(row["id"], "ses_fixture", "succeeded", "result")
        self.store.resume("ses_fixture")
        finished = self.store.finish(
            row["id"], "ses_fixture", "succeeded", "Verified result"
        )
        self.assertEqual(finished["state"], "waiting")
        self.assertTrue(finished["result"]["task_complete"])
        with self.assertRaises(PermissionError):
            self.store.finish(row["id"], "ses_other", "failed", "wrong conversation")

    def test_dst_and_coalesced_catchup(self):
        zone = ZoneInfo("Europe/Zurich")
        # 02:30 is absent in spring; advance to 03:00. Fall fold uses first 02:30.
        spring = wall_time(datetime(2026, 3, 29).date(), 2, 30, zone)
        self.assertEqual(
            datetime.fromtimestamp(spring, zone).strftime("%H:%M"), "03:00"
        )
        fall = wall_time(datetime(2026, 10, 25).date(), 2, 30, zone)
        self.assertEqual(datetime.fromtimestamp(fall, zone).fold, 0)
        now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()
        spec, due = normalize(dict(daily="02:30", timezone="Europe/Zurich"), now)
        self.assertEqual(due, fall)
        self.assertGreater(following(spec, due, due + 1), due + 20 * 3600)
        spec, due = normalize(dict(interval_seconds=60), 1000)
        self.assertEqual(following(spec, due, 1400), 1420)
        self.assertIsNone(following(dict(after_seconds=1), 1001, 2000))
        with self.assertRaises(ValueError):
            normalize(dict(at=None))


class EngineTests(Fixture, unittest.IsolatedAsyncioTestCase):
    async def test_paused_task_recovery_does_not_interrupt_explicit_chat(self):
        self.task()
        self.store.pause("ses_fixture")
        engine = Engine("fixture")
        call = AsyncMock(return_value=dict(active=True, chat_only=True))
        with (
            patch(
                "cosmos_tui.features.agent.tasks.runtime.descriptors",
                return_value=[dict(id="runtime")],
            ),
            patch("cosmos_tui.features.agent.tasks.runtime.call", call),
        ):
            await engine.step()
        self.assertFalse(any(c.args[1] == "interrupt" for c in call.await_args_list))
        self.assertTrue(self.store.paused("ses_fixture"))

    async def test_due_once_admitted_once_and_return_is_not_success(self):
        row = self.task(schedule=dict(after_seconds=1), next_run=1)
        engine = Engine("fixture")
        engine.tools.pane = AsyncMock(return_value=PANE)
        engine.notify = AsyncMock()
        calls = []

        async def call(desc, operation, conversation, **args):
            calls.append((operation, args))
            return dict(active=False, accepted=True)

        with (
            patch(
                "cosmos_tui.features.agent.tasks.runtime.find",
                AsyncMock(return_value=dict(id="runtime")),
            ),
            patch("cosmos_tui.features.agent.tasks.runtime.call", side_effect=call),
        ):
            await engine.step()
            self.assertEqual(self.store.get(row["id"])["state"], "running")
            await engine.step()
            self.assertEqual(self.store.get(row["id"])["state"], "needs_review")
            await engine.step()
        self.assertEqual(len([c for c in calls if c[0] == "wake"]), 1)
        self.assertFalse(self.store.get(row["id"])["result"]["task_complete"])

    async def test_manual_trigger_and_pause_never_wake_until_user_resume(self):
        row = self.task(mode="manual", schedule=dict(after_seconds=1), next_run=1)
        engine = Engine("fixture")
        engine.tools.pane = AsyncMock(return_value=PANE)
        engine.notify = AsyncMock()
        call = AsyncMock(return_value=dict(active=False, accepted=True))
        with (
            patch(
                "cosmos_tui.features.agent.tasks.runtime.find",
                AsyncMock(return_value=dict(id="runtime")),
            ),
            patch(
                "cosmos_tui.features.agent.tasks.runtime.descriptors",
                return_value=[dict(id="runtime")],
            ),
            patch("cosmos_tui.features.agent.tasks.runtime.call", call),
        ):
            await engine.step()
            self.assertEqual(self.store.get(row["id"])["state"], "needs_input")
            self.assertFalse(any(c.args[1] == "wake" for c in call.await_args_list))
            self.store.pause("ses_fixture")
            await engine.step()
            self.assertTrue(any(c.args[1] == "interrupt" for c in call.await_args_list))
            self.assertFalse(any(c.args[1] == "wake" for c in call.await_args_list))
            self.store.resume("ses_fixture")
            await engine.step()
            self.assertEqual(
                len([c for c in call.await_args_list if c.args[1] == "wake"]), 1
            )

    async def test_control_watch_wakes_and_private_or_replaced_target_blocks(self):
        row = self.task(kind="control", watch_id="watch_missing")
        engine = Engine("fixture")
        engine.tools.pane = AsyncMock(side_effect=ValueError("Private pane"))
        engine.notify = AsyncMock()
        call = AsyncMock(return_value=dict(active=False, accepted=True))
        with (
            patch(
                "cosmos_tui.features.agent.tasks.runtime.find",
                AsyncMock(return_value=dict(id="runtime")),
            ),
            patch("cosmos_tui.features.agent.tasks.runtime.call", call),
        ):
            await engine.step()
        self.assertEqual(self.store.get(row["id"])["state"], "blocked")
        self.assertFalse(any(c.args[1] == "wake" for c in call.await_args_list))


class PopupTests(Fixture, unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_setting_cycles_in_private_store(self):
        from cosmos_tui.features.settings.panel import Palette
        from test_navigation import snapshot

        with patch("cosmos_tui.core.rpc.call", AsyncMock(return_value=snapshot())):
            app = Probe()
            async with app.run_test(size=(110, 36)) as pilot:
                app.push_screen(Palette("task_settings"))
                await pilot.pause()
                panel = app.screen
                row = next(r for r in panel.rows if r.get("key") == "max_models")
                self.assertEqual(row["value"], 2)
                await panel.cycle_choice(row, 1)
                self.assertEqual(Tasks(app.backend.argv[2]).settings()["max_models"], 3)

    async def test_transparent_popup_selection_buttons_and_independent_spinner(self):
        app = Probe()
        async with app.run_test(size=(110, 36)) as pilot:
            store = Tasks(app.backend.argv[2])
            row = store.create("ses_fixture", "runtime", PANE, "Task fixture")
            app.push_screen(TaskPanel())
            await pilot.pause()
            panel = app.screen
            self.assertIsInstance(panel, TaskPanel)
            self.assertEqual(panel.styles.background.a, 0)
            self.assertTrue(panel.preserve_workspace_graphics)
            self.assertEqual(len(panel.graphics_covers()), 1)
            self.assertGreater(panel.query_one(ListView).size.height, 0)
            await pilot.press("p")
            await pilot.pause()
            self.assertEqual(store.get(row["id"])["state"], "paused")
            await pilot.press("q")
            await pilot.pause()
            self.assertIs(app.screen, app._workspace_screen)
            # The header timer invalidates terminal rows independently of app.tick().
            from dataclasses import replace

            app.panes = [replace(app.panes[0], y=1)]
            controller = HeaderController(app)
            app._agent_headers = {"%0": dict(state="active", task="Task")}
            surface = app.query_one("#terminal")
            with patch.object(surface, "refresh") as refresh:
                await asyncio.sleep(0.32)
                self.assertGreaterEqual(refresh.call_count, 2)
            controller.timer.stop()
            palette = app.role_colors
            first = header_text(dict(state="active", task="Task"), 90, palette, 0).plain
            second = header_text(
                dict(state="active", task="Task"), 90, palette, 1
            ).plain
            paused = header_text(
                dict(state="paused", task="Task"), 90, palette, 1
            ).plain
            self.assertNotEqual(first, second)
            self.assertIn("⏸", paused)
            app.push_screen(TaskText("History", json.dumps(store.history(row["id"]))))
            await pilot.pause()
            self.assertEqual(app.screen.styles.background.a, 0)
            self.assertLess(app.screen.query_one("#task-text-frame").size.width, 110)


class BashAdapterTests(Fixture, unittest.IsolatedAsyncioTestCase):
    async def test_real_bash_prompt_event_matches_without_screen_guessing(self):
        import shutil
        import uuid
        from cosmos_tui.features.agent.terminal import TerminalTools

        if not shutil.which("tmux"):
            self.skipTest("requires tmux")
        tools = TerminalTools("task-bash-" + uuid.uuid4().hex)
        root = Path(__file__).resolve().parents[1]
        try:
            await tools.backend.cli(
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-s",
                "fixture",
                f"bash --rcfile {root}/config/cosmosrc -i",
            )
            pane = (await tools.panes())[0]["pane_id"]
            from cosmos_tui.features.agent.monitor.bash import prompt_stamp

            for _ in range(80):
                if await prompt_stamp(tools, pane):
                    break
                await asyncio.sleep(0.05)
            self.assertIsNotNone(await prompt_stamp(tools, pane))
            watch = await tools.watch_terminal(pane, "bash_prompt", timeout_seconds=8)
            await tools.send_text(pane, ":")
            await tools.send_keys(pane, ["Enter"])
            for _ in range(80):
                result = next(
                    r for r in await tools.terminal_watches() if r["id"] == watch["id"]
                )
                if result["state"] != "waiting":
                    break
                await asyncio.sleep(0.1)
            self.assertEqual(result["state"], "matched")
            self.assertEqual(result["result"]["source"], "bash_prompt_adapter")
        finally:
            await tools.backend.cli("kill-server")


if __name__ == "__main__":
    unittest.main()
