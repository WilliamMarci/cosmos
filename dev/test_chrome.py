"""Settings frames and compact controls use the same UI surface."""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / n) for n in ("python", "terminal_agent")
]
from textual.app import App  # noqa: E402
from cosmos_tui.app import Cosmos  # noqa: E402
from cosmos_tui.app import Palette  # noqa: E402
from cosmos_tui.app import Help  # noqa: E402
from cosmos_tui.app import DARK  # noqa: E402
from cosmos_tui.ui.chrome import Frame  # noqa: E402
from textual.widgets import Input  # noqa: E402


class Probe(App):
    CSS = Cosmos.CSS
    prefix = False
    client = "test-chrome"
    role_colors = DARK

    async def on_mount(self):
        await self.push_screen(Palette())


class ChromeTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_title_in_border_and_filter_inside_frame(self):
        snapshot = dict(
            actions=[
                dict(
                    category="actions", label="Settings", kind="menu", menu="settings"
                ),
                dict(category="settings", label="Display", kind="menu", menu="display"),
            ],
            mods=[],
        )
        with patch("cosmos_tui.core.rpc.call", AsyncMock(return_value=snapshot)):
            app = Probe()
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                self.assertEqual(app.screen.menu, "settings")
                frame = app.screen.query_one(Frame)
                self.assertEqual(frame.border_title, "Cosmos / settings")
                self.assertEqual(frame.styles.border_top[0], "round")
                self.assertGreater(app.screen.query_one(Input).region.y, frame.region.y)
                self.assertIn("settings", app.export_screenshot())

    async def test_keybinding_help_uses_shared_frame_and_palette_hides_raw_backend(
        self,
    ):
        snapshot = dict(
            actions=[
                dict(
                    id="objects.list",
                    category="actions",
                    label="Terminal panes",
                    kind="rpc",
                ),
                dict(
                    id="keys.apply",
                    category="keys",
                    label="Apply keybindings now",
                    kind="rpc",
                ),
            ],
            mods=[],
        )
        with patch("cosmos_tui.core.rpc.call", AsyncMock(return_value=snapshot)):
            app = Probe()
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                rows = app.screen.rows
                self.assertFalse(any(row.get("id") == "objects.list" for row in rows))
                self.assertFalse(
                    any(row.get("kind") in ("local", "mod") for row in rows)
                )
                await app.push_screen(Help("Keybindings", [("Leader s", "Switch")]))
                await pilot.pause()
                frame = app.screen.query_one(Frame)
                self.assertEqual(frame.id, "help-frame")
                self.assertIn("┐ Keybindings", frame.border_strip(True).text)


if __name__ == "__main__":
    unittest.main()
