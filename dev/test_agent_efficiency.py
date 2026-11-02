"""Focused task-accounting and incremental-output regressions; no model calls."""

import os
import pathlib
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from cosmos_tui.features.agent.compact import step_observation
from cosmos_tui.features.agent.control import ControlStore
from cosmos_tui.features.agent.control_tools import ControlledInput
from cosmos_tui.features.agent.tasks.storage import Tasks


def snapshot(identity, rows, width=80):
    return dict(
        pane="%1",
        snapshot_id=identity,
        text=[dict(y=i + 1, x=1, text=t) for i, t in enumerate(rows)],
        dimensions=dict(width=width, height=24),
        region=dict(x=1, y=1, width=width, height=24),
        cursor=dict(x=1, y=1),
        coordinate_space="application_content_cells_1based",
        truncated=False,
        program="bash",
    )


class DeltaTests(unittest.TestCase):
    def test_changed_and_cleared_rows_and_layout_reset(self):
        cache = {}
        self.assertEqual(
            step_observation(cache, snapshot("a", ["same", "old"]))["mode"], "snapshot"
        )
        changed = step_observation(cache, snapshot("b", ["same", "new"]))
        self.assertEqual(changed["text"], [dict(y=2, x=1, text="new")])
        self.assertEqual(changed["base_snapshot_id"], "a")
        cleared = step_observation(cache, snapshot("c", ["same"]))
        self.assertEqual(cleared["cleared_rows"], [2])
        self.assertEqual(
            step_observation(cache, snapshot("d", ["same"], 40))["mode"], "snapshot"
        )
        self.assertEqual(
            step_observation(cache, snapshot("e", ["same"]), full=True)["mode"], "full"
        )

    def test_truncated_delivery_never_becomes_complete_delta_baseline(self):
        cache = {}
        rows = ["x" * 200 for _ in range(40)]
        self.assertTrue(step_observation(cache, snapshot("a", rows))["truncated"])
        self.assertEqual(
            step_observation(cache, snapshot("b", rows))["mode"], "snapshot"
        )


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            XDG_RUNTIME_DIR=self.tmp.name,
            COSMOS_TASKS_HOME=self.tmp.name + "/tasks",
        )
        self.env.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.env.stop)
        self.tools = ControlledInput()
        self.tools.backend = SimpleNamespace(argv=["tmux", "-L", "efficiency"])
        self.tools.owner = "ours"
        self.tools.observation_requests = {"a": ("%1", None)}
        self.tools.observe = AsyncMock(return_value=snapshot("a", ["hello"]))
        self.tools.pane = AsyncMock(
            return_value=dict(
                pane_id="%1", pid="10", window_id="@1", pane_width=80, pane_height=24
            )
        )
        self.tools.control_tokens = {}
        self.tools.control_geometry = {}

    async def test_conflict_never_creates_task(self):
        ControlStore("efficiency").acquire("%1", "other", "Task")
        with self.assertRaises(ValueError):
            await self.tools.acquire_control("%1", "a", "Task")
        self.assertEqual(Tasks("efficiency").list(), [])

    async def test_observation_failure_never_creates_task(self):
        self.tools.observe.side_effect = [
            snapshot("a", ["hello"]),
            RuntimeError("capture failed"),
        ]
        with patch("cosmos_tui.features.agent.headers.synchronize"):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                await self.tools.acquire_control("%1", "a", "Task")
        self.assertEqual(ControlStore("efficiency").status(), [])
        self.assertEqual(Tasks("efficiency").list(), [])

    async def test_authorize_control_returns_a_bounded_allowance(self):
        allowed = await self.tools.authorize_control(
            "%1", ["observe output", "run tests"], 600
        )
        self.assertEqual(allowed["state"], "allowed")
        self.assertEqual(allowed["operations"], ["observe output", "run tests"])
        self.assertEqual(allowed["seconds"], 600)
        with self.assertRaises(ValueError):
            await self.tools.authorize_control("%1", [], 600)
        with self.assertRaises(ValueError):
            await self.tools.authorize_control("%1", ["run"], 5)

    async def test_repeated_release_cannot_release_replacement(self):
        store = ControlStore("efficiency")
        old = store.acquire("%1", "ours", "Old")
        with patch("cosmos_tui.features.agent.headers.synchronize"):
            await self.tools.release_control("%1", old["token"])
            new = store.acquire("%1", "ours", "New")
            self.tools.control_tokens["%1"] = new["token"]
            result = await self.tools.release_control("%1", old["token"])
            self.assertTrue(result["already_finished"])
            self.assertEqual(self.tools.control_tokens["%1"], new["token"])
            store.guarded("%1", "ours", new["token"], lambda: None)
            with self.assertRaises(ValueError):
                await self.tools.release_control("%1", "unknown")


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_returns_resume_challenge_without_action_catalog(self):
        from cosmos_tui.features.agent.context import ContextTools
        from cosmos_tui.features.agent.actions import ActionTools

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_RUNTIME_DIR=directory),
        ):
            tools = ContextTools()
            tools.backend = SimpleNamespace(argv=["tmux", "-L", "context-test"])
            tools.binding = object()
            tools.owner = "ours"
            tools.control_tokens = {}
            tools.conversation = "session"
            tools.redact = lambda value: value
            tools.observe = AsyncMock(return_value=snapshot("context", ["prompt"]))
            tools.panes = AsyncMock(
                return_value=[
                    dict(
                        pane_id="%1",
                        display_id="0:1",
                        window_index=4,
                        pane_index=2,
                        session_name="main",
                        private=False,
                        pane_current_path="/tmp",
                        pane_current_command="bash",
                    )
                ]
            )
            tools.list_tasks = AsyncMock(
                return_value=[
                    dict(
                        id="task",
                        pane="%1",
                        state="paused",
                        revision=3,
                        goal="Check result",
                        resume_challenge="challenge",
                        runtime="hidden",
                    )
                ]
            )
            with (
                patch.object(
                    ActionTools,
                    "clients",
                    AsyncMock(return_value={"mobile": "socket1", "desktop": "socket2"}),
                ),
                patch.object(
                    ActionTools,
                    "list_actions",
                    AsyncMock(side_effect=AssertionError("must not enumerate actions")),
                ),
            ):
                result = await tools.context("0:1")
                self.assertEqual(result["status"], "paused")
                self.assertEqual(result["target"]["position"], "4:2")
                self.assertEqual(result["target"]["pane"], "%1")
                self.assertEqual(result["tasks"][0]["resume_challenge"], "challenge")
                self.assertNotIn("runtime", result["tasks"][0])
                self.assertIsNone(result["client"])
                self.assertEqual(result["next"], "request_resume")
                missing = await tools.context("9:9", client="disconnected")
                self.assertEqual(missing["status"], "target_not_found")
                self.assertEqual(missing["targets"][0]["display_id"], "0:1")

    async def test_mcp_conflict_has_machine_readable_next_step(self):
        import json
        from cosmos_tui.features.agent.control import ControlUnavailable
        from cosmos_tui.features.agent.mcp import dispatch

        tools = SimpleNamespace(
            acquire_control=AsyncMock(
                side_effect=ControlUnavailable(
                    "owned_by_other",
                    "Pane already controlled",
                    "wait_or_choose_another_target",
                )
            )
        )
        result = await dispatch(
            tools,
            dict(
                method="tools/call",
                params=dict(
                    name="acquire_control",
                    arguments=dict(pane="%1", snapshot_id="a", label="test"),
                ),
            ),
        )
        self.assertTrue(result["isError"])
        self.assertEqual(
            json.loads(result["content"][0]["text"])["status"], "owned_by_other"
        )


class ContextSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_auto_injects_one_matching_software_skill(self):
        from cosmos_tui.features.agent.context import ContextTools
        from cosmos_tui.features.agent.actions import ActionTools

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                XDG_RUNTIME_DIR=directory,
                XDG_CONFIG_HOME=directory,
            ),
        ):
            source = (
                pathlib.Path(directory)
                / "cosmos/agent/skills/vim-search"
            )
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\n"
                "name: vim-search\n"
                "description: Search in Vim.\n"
                "metadata:\n"
                "  cosmos/software: [vim, nvim]\n"
                "---\n\n"
                "# Vim\n\nUse `/` and `n`.\n"
            )
            tools = ContextTools()
            tools.backend = SimpleNamespace(argv=["tmux", "-L", "context-skill"])
            tools.binding = object()
            tools.owner = "ours"
            tools.control_tokens = {}
            tools.redact = lambda value: value
            tools.observe = AsyncMock(return_value=snapshot("skill", ["vim"]))
            tools.panes = AsyncMock(
                return_value=[
                    dict(
                        pane_id="%1",
                        display_id="0:1",
                        session_name="main",
                        private=False,
                        pane_current_path=directory,
                        pane_current_command="vim",
                    )
                ]
            )
            with (
                patch.object(
                    ActionTools,
                    "clients",
                    AsyncMock(return_value={"desktop": "socket"}),
                ),
                patch.object(
                    ActionTools,
                    "client_context",
                    AsyncMock(return_value=dict(active_pane="%1", context="workspace")),
                ),
            ):
                result = await tools.context()
                self.assertEqual(result["target"]["skill"]["name"], "vim-search")
                self.assertIn("Use `/`", result["target"]["skill"]["content"])
                again = await tools.context()
                self.assertNotIn("skill", again["target"])
                self.assertEqual(
                    again["target"]["recommended_skills"][0]["name"], "vim-search"
                )

    async def test_active_client_target_summary_and_private_boundary(self):
        from cosmos_tui.features.agent.context import ContextTools
        from cosmos_tui.features.agent.actions import ActionTools

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_RUNTIME_DIR=directory),
        ):
            tools = ContextTools()
            tools.backend = SimpleNamespace(argv=["tmux", "-L", "context-summary"])
            tools.binding = object()
            tools.owner = "ours"
            tools.control_tokens = {}
            tools.redact = lambda value: value
            row = dict(
                pane_id="%1",
                display_id="0:1",
                session_name="main",
                private=False,
                pane_current_path="/tmp",
                pane_current_command="bash",
            )
            tools.panes = AsyncMock(return_value=[row])
            tools.observe = AsyncMock(
                return_value=snapshot("recent", ["x" * 200 for _ in range(20)])
            )
            with (
                patch.object(
                    ActionTools,
                    "clients",
                    AsyncMock(return_value={"desktop": "socket"}),
                ),
                patch.object(
                    ActionTools,
                    "client_context",
                    AsyncMock(return_value=dict(active_pane="%1", context="workspace")),
                ),
            ):
                result = await tools.context()
                self.assertEqual(result["target"]["pane"], "%1")
                self.assertLessEqual(
                    sum(len(r["text"].encode()) for r in result["recent"]["text"]), 1024
                )
                self.assertLessEqual(len(result["recent"]["text"]), 8)
                self.assertIn(
                    "cosmos_control", [r["tool"] for r in result["allowed_next"]]
                )
                row["private"] = True
                row["pane_current_path"] = row["pane_current_command"] = ""
                tools.observe.reset_mock()
                private = await tools.context()
                self.assertEqual(private["status"], "private")
                self.assertIsNone(private["recent"])
                self.assertEqual(private["allowed_next"], [])
                tools.observe.assert_not_awaited()
            row["private"] = False
            with (
                patch.object(
                    ActionTools,
                    "clients",
                    AsyncMock(return_value={"desktop": "socket", "mobile": "socket2"}),
                ),
                patch.object(
                    ActionTools,
                    "client_context",
                    AsyncMock(side_effect=OSError("connection refused")),
                ),
            ):
                disconnected = await tools.context(client="desktop")
                self.assertEqual(disconnected["clients"], ["mobile"])
                self.assertIsNone(disconnected["client"])
                self.assertIn("connection refused", disconnected["client_error"])
