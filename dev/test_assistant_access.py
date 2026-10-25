"""Command assistant settings and generation-time policy propagation."""

import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from test_navigation import Probe, snapshot
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.assistant.presenter import ContextBackend, GuardedBackend
from textual.widgets import ListView


class AssistantAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_cycles_and_reopens_saved_policy(self):
        state = snapshot()
        state["settings"]["assistant_file_access"] = "read_only"

        async def rpc(method, params=None):
            if method == "state.snapshot":
                return copy.deepcopy(state)
            if method == "settings.get":
                return copy.deepcopy(state["settings"])
            if method == "settings.replace":
                state["settings"] = copy.deepcopy(params)
                return {}
            return []

        app = Probe()
        with patch("cosmos_tui.core.rpc.call", side_effect=rpc):
            async with app.run_test(size=(100, 35)) as pilot:
                app.push_screen(Palette())
                await pilot.pause()
                menu = app.screen
                menu.query_one(ListView).index = next(
                    i
                    for i, r in enumerate(menu.rows)
                    if r["label"] == "Command assistant"
                )
                await pilot.press("full_stop")
                self.assertEqual(menu.menu, "assistant_settings")
                for expected in ("read_write", "none", "read_only"):
                    await pilot.press("right")
                    self.assertEqual(
                        state["settings"]["assistant_file_access"], expected
                    )
                    self.assertEqual(app.settings["assistant_file_access"], expected)
                await pilot.press("left")
                self.assertEqual(state["settings"]["assistant_file_access"], "none")
                await pilot.press("comma")
                menu.query_one(ListView).index = next(
                    i
                    for i, r in enumerate(menu.rows)
                    if r["label"] == "Command assistant"
                )
                await pilot.press("full_stop")
                self.assertEqual(menu.rows[0]["value"], "none")

    async def test_open_assistant_uses_policy_at_each_generation(self):
        backend = SimpleNamespace(config={}, propose=AsyncMock(return_value="ls"))
        presenter = SimpleNamespace(
            request_version=1,
            finished=False,
            app=SimpleNamespace(settings={}),
            source=lambda: SimpleNamespace(active=True),
        )
        guarded = GuardedBackend(presenter, ContextBackend(backend, "/tmp/target"))
        for mode in ("none", "read_only", "read_write"):
            presenter.app.settings["assistant_file_access"] = mode
            self.assertEqual(await guarded.propose([]), "ls")
            self.assertEqual(backend.config["file_access"], mode)
            backend.propose.assert_awaited_with([], cwd="/tmp/target")
