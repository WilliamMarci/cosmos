"""Child-app key conflicts, local escape chord and resuming Cosmos actions."""

import unittest
from unittest.mock import AsyncMock

from test_navigation import Probe
from cosmos_tui.features.navigation.menus import ActionDrawer
from cosmos_tui.features.status.bar import StatusBar


class PassthroughTests(unittest.IsolatedAsyncioTestCase):
    async def test_suspend_forward_and_resume(self):
        app = Probe()
        async with app.run_test(size=(110, 30)) as pilot:
            app.backend.send = AsyncMock()
            app.ime.handle = AsyncMock(return_value=False)
            await pilot.press("ctrl+b", "f12")
            self.assertTrue(app.inputs.keyboard_passthrough)
            app.ime.handle.reset_mock()
            await pilot.press("ctrl+p", "ctrl+b", "s", "x")
            self.assertFalse(isinstance(app.screen, ActionDrawer))
            self.assertEqual(
                [call.args[0] for call in app.backend.send.await_args_list],
                ["ctrl+p", "ctrl+b", "s", "x"],
            )
            app.ime.handle.assert_not_awaited()
            bar = app.query_one("#status", StatusBar)
            bar.present(
                label="COSMOS", index=0, name="bash", path="", branch="", clock="12:00"
            )
            self.assertIn("bash KEYS OFF", bar._content.plain)
            offset = bar._content.plain.index("KEYS OFF")
            self.assertTrue(bar._content.get_style_at_offset(app.console, offset).bold)
            await pilot.press("ctrl+b", "f12")
            self.assertFalse(app.inputs.keyboard_passthrough)
            await pilot.press("ctrl+p")
            self.assertIsInstance(app.screen, ActionDrawer)

    async def test_rebound_escape_chord(self):
        app = Probe()
        async with app.run_test(size=(100, 30)) as pilot:
            app.settings.setdefault("keybindings", {})[
                "global.keyboard_passthrough"
            ] = ["ctrl+g"]
            app.backend.send = AsyncMock()
            await pilot.press("ctrl+g")
            self.assertTrue(app.inputs.keyboard_passthrough)
            await pilot.press("ctrl+p", "ctrl+g")
            self.assertFalse(app.inputs.keyboard_passthrough)
            self.assertEqual(app.backend.send.await_args_list[0].args[0], "ctrl+p")
