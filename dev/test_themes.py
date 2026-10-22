# ruff: noqa: E402
"""Independent terminal/UI color semantics and theme chooser transaction."""

import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe, snapshot
from cosmos_tui.features.theme.palettes import terminal_palette, terminal_style
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.ui.styles import DARK
from rich.style import Style
from rich.color import ColorType
from textual.widgets import ListView


class ThemeTests(unittest.IsolatedAsyncioTestCase):
    def test_native_defaults_and_explicit_truecolor_are_preserved(self):
        native = terminal_palette("inherit")
        result = terminal_style(Style(color="red"), native)
        self.assertEqual(result.color.type, ColorType.STANDARD)
        self.assertEqual(result.bgcolor.type, ColorType.DEFAULT)
        explicit = Style(color="#123456", bgcolor="#abcdef", bold=True)
        self.assertEqual(terminal_style(explicit, terminal_palette("ubuntu")), explicit)
        ubuntu = terminal_style(Style(color="red"), terminal_palette("ubuntu"))
        self.assertEqual(ubuntu.color.name, "#cc0000")
        self.assertEqual(ubuntu.bgcolor.name, "#300a24")

    async def test_preview_cancel_then_independent_save(self):
        settings = dict(theme="dark", terminal_theme="inherit", leader="C-b")

        async def rpc(method, params=None):
            if method == "state.snapshot":
                return snapshot()
            if method == "settings.get":
                return dict(settings)
            if method == "settings.replace":
                settings.update(params)
                return {}
            return {}

        with patch("cosmos_tui.core.rpc.call", AsyncMock(side_effect=rpc)):
            app = Probe()
            app.settings.update(settings)
            async with app.run_test(size=(100, 34)) as pilot:
                await pilot.press("ctrl+b", "p", *"theme", "enter")
                self.assertIsInstance(app.screen, ThemePanel)
                panel = app.screen
                panel.query_one("#terminal-themes", ListView).index = 1
                panel.query_one("#ui-themes", ListView).index = 1
                await pilot.pause()
                self.assertEqual(app.settings["terminal_theme"], "inherit")
                self.assertEqual(app.role_colors, DARK)
                await pilot.press("escape")
                self.assertEqual(settings["terminal_theme"], "inherit")
                app.push_screen(ThemePanel())
                await pilot.pause()
                app.screen.query_one("#terminal-themes", ListView).index = 1
                await pilot.press("tab", "tab", "enter")
                await pilot.pause()
                self.assertEqual(settings["terminal_theme"], "ubuntu")
                self.assertEqual(settings["theme"], "dark")


if __name__ == "__main__":
    unittest.main()
