"""Shared native header geometry, restoration and local rendering."""

import os
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

from rich.console import Console
from textual.strip import Strip
from types import SimpleNamespace

from cosmos_tui.features.agent.terminal import TerminalTools
from cosmos_tui.features.agent.control import ControlStore
from cosmos_tui.features.agent.headers import synchronize
from cosmos_tui.features.agent.header_ui import header_text, paint_headers
from cosmos_tui.features.agent.tasks.storage import Tasks
from cosmos_tui.ui.styles import DARK


class HeaderRenderTests(unittest.TestCase):
    def test_busy_indicator_keeps_low_frequency_feedback_and_block_boundary(self):
        from cosmos_tui.features.agent.header_ui import activity_frame

        with patch(
            "cosmos_tui.features.agent.header_ui.time.monotonic", return_value=10.0
        ):
            first = activity_frame(True)
        with patch(
            "cosmos_tui.features.agent.header_ui.time.monotonic", return_value=10.6
        ):
            second = activity_frame(True)
        self.assertNotEqual(first, second)
        line = header_text(dict(state="active", task="Task"), 60, DARK, first)
        self.assertNotIn("│", line.plain)
        segments = list(line.render(Console(), end=""))
        backgrounds = {segment.style.bgcolor for segment in segments if segment.style}
        self.assertGreaterEqual(len(backgrounds), 2)

    def test_paused_is_static_and_does_not_cover_content(self):
        paused = dict(state="paused", task="Task")
        a = header_text(paused, 40, DARK, 0)
        b = header_text(paused, 40, DARK, 4)
        self.assertEqual(a, b)
        self.assertIn("COSMOS PAUSED", a.plain)
        app = SimpleNamespace(
            panes=[SimpleNamespace(id="%0", x=0, y=1, width=40)],
            _agent_headers={"%0": paused},
            role_colors=DARK,
            console=Console(),
        )
        self.assertIn("PAUSED", paint_headers(app, Strip.blank(40), 0, 40).text)
        content = Strip.blank(40)
        self.assertEqual(paint_headers(app, content, 1, 40).text, content.text)
        self.assertNotEqual(
            header_text(dict(state="active", task="Task"), 60, DARK, 0),
            header_text(dict(state="active", task="Task"), 60, DARK, 1),
        )


@unittest.skipUnless(shutil.which("tmux"), "requires tmux")
class HeaderTmuxTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_panes_share_one_reservation_and_restore_inheritance(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                XDG_RUNTIME_DIR=directory,
                COSMOS_TASKS_HOME=directory + "/tasks",
            ),
        ):
            socket = "cosmos-header-" + uuid.uuid4().hex
            tool = TerminalTools(socket)
            cli = tool.backend.cli
            try:
                await cli(
                    "-f",
                    "/dev/null",
                    "new-session",
                    "-d",
                    "-s",
                    "test",
                    "-x",
                    "100",
                    "-y",
                    "30",
                    "bash --noprofile --norc",
                )
                await cli("split-window", "-h", "bash --noprofile --norc")
                rows = await tool.panes()
                first, second = rows
                window = first["window_id"]
                before = first["pane_height"]
                store = ControlStore(socket)
                one = store.acquire(first["pane_id"], "owner", "Task one", first["pid"])
                synchronize(tool.backend.argv)
                self.assertEqual(
                    (await tool.pane(first["pane_id"]))["pane_height"], before - 1
                )
                two = store.acquire(
                    second["pane_id"], "owner", "Task two", second["pid"]
                )
                synchronize(tool.backend.argv)
                self.assertEqual(
                    (await tool.pane(first["pane_id"]))["pane_height"], before - 1
                )
                store.change(first["pane_id"], "pause")
                states = synchronize(tool.backend.argv)
                self.assertEqual(
                    next(r for r in states if r["pane"] == first["pane_id"])["state"],
                    "paused",
                )
                store.release(first["pane_id"], "owner", one["token"])
                synchronize(tool.backend.argv)
                self.assertEqual(
                    (await tool.pane(second["pane_id"]))["pane_height"], before - 1
                )
                store.release(second["pane_id"], "owner", two["token"])
                synchronize(tool.backend.argv)
                self.assertEqual(
                    (await tool.pane(second["pane_id"]))["pane_height"], before
                )
                task_store = Tasks(socket)
                task = task_store.create(
                    "conversation", "runtime", first, "Task header", kind="schedule"
                )
                states = synchronize(tool.backend.argv)
                self.assertEqual(
                    next(r for r in states if r["pane"] == first["pane_id"])["state"],
                    "active",
                )
                self.assertEqual(
                    (await tool.pane(first["pane_id"]))["pane_height"], before - 1
                )
                task_store.change(task["id"], state="cancelled")
                task_store.delete(task["id"])
                synchronize(tool.backend.argv)
                self.assertEqual(
                    (await tool.pane(first["pane_id"]))["pane_height"], before
                )
                self.assertEqual(
                    await cli("show-options", "-w", "-t", window, "pane-border-status"),
                    "",
                )
                self.assertNotIn(
                    "@cosmos_control_header",
                    await cli("show-options", "-w", "-t", window),
                )
                # An explicit previous override must also be restored.
                await cli(
                    "set-option", "-w", "-t", window, "pane-border-status", "bottom"
                )
                lease = store.acquire(first["pane_id"], "owner", "Again", first["pid"])
                synchronize(tool.backend.argv)
                store.release(first["pane_id"], "owner", lease["token"])
                synchronize(tool.backend.argv)
                self.assertEqual(
                    (
                        await cli(
                            "show-options", "-wv", "-t", window, "pane-border-status"
                        )
                    ).strip(),
                    "bottom",
                )
            finally:
                await cli("kill-server")


class HeaderUITests(unittest.IsolatedAsyncioTestCase):
    async def test_native_surface_shows_header_without_replacing_terminal_text(self):
        from test_navigation import Probe
        from test_assistant import rendered_text
        from cosmos_tui.terminal.tmux import Pane
        from cosmos_tui.render.surface import TerminalSurface
        from rich.text import Text

        app = Probe()
        async with app.run_test(size=(100, 30)) as pilot:
            app.panes = [Pane("%0", 0, 1, 100, 27, True, [], "", (0, 0))]
            app.lines = {"%0": [Text("APPLICATION_CONTENT_SENTINEL")]}
            app._agent_headers = {"%0": dict(state="active", task="Inspecting Vim")}
            app.query_one(TerminalSurface).refresh()
            await pilot.pause()
            shown = rendered_text(app)
            self.assertIn("Taking over", shown)
            self.assertIn("APPLICATION_CONTENT_SENTINEL", shown)
            app._agent_headers["%0"]["state"] = "paused"
            app.query_one(TerminalSurface).refresh()
            await pilot.pause()
            shown = rendered_text(app)
            self.assertIn("PAUSED", shown)
            self.assertNotIn("Taking over", shown)
            self.assertIn("APPLICATION_CONTENT_SENTINEL", shown)


class AgentPointerTests(unittest.TestCase):
    def test_pointer_is_independent_and_hidden_when_paused_or_resized(self):
        from cosmos_tui.features.agent.header_ui import pointer_cell

        pane = SimpleNamespace(id="%0", x=0, y=1, width=40, height=20)
        record = dict(
            state="active", task="Task", pointer=dict(x=4, y=3, width=40, height=20)
        )
        app = SimpleNamespace(
            panes=[pane],
            _agent_headers={"%0": record},
            role_colors=DARK,
            console=Console(),
            settings=dict(reduced_motion=True),
        )
        self.assertEqual(pointer_cell(record, pane), (3, 3))
        original = Strip.blank(40)
        self.assertEqual(paint_headers(app, original, 3, 40).text[3], "◆")
        record["state"] = "paused"
        self.assertIsNone(pointer_cell(record, pane))
        self.assertNotIn("◆", paint_headers(app, original, 3, 40).text)
        record["state"] = "active"
        pane.height = 19
        self.assertIsNone(pointer_cell(record, pane))
