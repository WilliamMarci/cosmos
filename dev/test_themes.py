# ruff: noqa: E402
"""Independent terminal/UI color semantics and theme chooser transaction."""

import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe, snapshot
from cosmos_tui.features.theme.catalog import (
    cosmos_theme,
    reload_themes,
    terminal_theme,
)
from cosmos_tui.features.theme.palettes import terminal_palette, terminal_style
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.core.paths import ASSET_DIR
from cosmos_tui.ui.logo import DEFAULT_LOGO, render_logo
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

    def test_builtin_catalog_and_four_icon_colors(self):
        catalog = reload_themes()
        terminal_ids = {theme.id for theme in catalog.terminals}
        interface_ids = {theme.id for theme in catalog.interfaces}
        self.assertTrue(
            {"solarized-dark", "solarized-light", "gruvbox-dark", "nord"}
            <= terminal_ids
        )
        self.assertTrue({"midnight", "paper"} <= interface_ids)
        self.assertEqual(catalog.errors, ())
        nord = terminal_theme("nord")
        self.assertEqual(nord.bg, "#2e3440")
        self.assertEqual(len(nord.ansi), 16)
        midnight = cosmos_theme("midnight")
        self.assertEqual(len(midnight.logo.foreground), 2)
        self.assertEqual(len(midnight.logo.background), 2)
        self.assertEqual(
            set(
                (
                    *midnight.logo.foreground,
                    *midnight.logo.background,
                )
            ),
            {"#c4a7e7", "#7aa2f7", "#241b3a", "#101a33"},
        )
        self.assertEqual(
            render_logo(DEFAULT_LOGO),
            (ASSET_DIR / "cosmos-logo.ansi").read_text(),
        )
        self.assertNotEqual(render_logo(DEFAULT_LOGO), render_logo(midnight.logo))

    def test_user_theme_folder_loads_overrides_and_reports_errors(self):
        try:
            with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": directory}
            ):
                folder = Path(directory) / "cosmos/themes"
                folder.mkdir(parents=True)
                (folder / "custom.toml").write_text(
                    "\n".join(
                        [
                            'kind = "terminal"',
                            'name = "Custom Terminal"',
                            'fg = "#EEEEEE"',
                            'bg = "#111111"',
                            "ansi = [",
                            *(
                                '  "#000000", "#111111", "#222222", "#333333",'
                                for _ in range(4)
                            ),
                            "]",
                        ]
                    )
                )
                (folder / "dark.toml").write_text(
                    "\n".join(
                        [
                            'kind = "cosmos"',
                            'name = "User Dark"',
                            "[colors]",
                            'bg = "#010203"',
                            'base = "#040506"',
                            'fg = "#070809"',
                            'mute = "#0A0B0C"',
                            'acc = "#0D0E0F"',
                            'accl = "#101112"',
                            'on = "#131415"',
                            "[logo]",
                            'foreground = ["#AABBCC", "#DDEEFF"]',
                            'background = ["#112233", "#445566"]',
                            'mode = "radial"',
                            "steps = 12",
                        ]
                    )
                )
                (folder / "broken.toml").write_text('kind = "terminal"\nfg = "red"\n')
                catalog = reload_themes()
                self.assertEqual(terminal_theme("custom").name, "Custom Terminal")
                self.assertEqual(cosmos_theme("dark").name, "User Dark")
                self.assertEqual(cosmos_theme("dark").logo.mode, "radial")
                self.assertTrue(any("broken.toml" in error for error in catalog.errors))
        finally:
            reload_themes()

    def test_templates_are_not_loaded(self):
        catalog = reload_themes()
        self.assertNotIn("terminal", {theme.id for theme in catalog.terminals})
        self.assertNotIn("cosmos", {theme.id for theme in catalog.interfaces})

    async def test_theme_panel_reload_picks_up_user_file(self):
        try:
            with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"XDG_CONFIG_HOME": directory}
            ):
                folder = Path(directory) / "cosmos/themes"
                folder.mkdir(parents=True)
                app = Probe()
                app.settings.update(theme="dark", terminal_theme="inherit")
                async with app.run_test(size=(100, 34)) as pilot:
                    app.push_screen(ThemePanel())
                    await pilot.pause()
                    panel = app.screen
                    self.assertNotIn(
                        "later", [theme_id for theme_id, _ in panel.terminals]
                    )
                    (folder / "later.toml").write_text(
                        "\n".join(
                            [
                                'kind = "terminal"',
                                'name = "Later"',
                                'fg = "#FFFFFF"',
                                'bg = "#000000"',
                                "ansi = [",
                                *(
                                    '  "#000000", "#111111", "#222222", "#333333",'
                                    for _ in range(4)
                                ),
                                "]",
                            ]
                        )
                    )
                    await pilot.press("r")
                    await pilot.pause()
                    self.assertIn(
                        "later", [theme_id for theme_id, _ in panel.terminals]
                    )
                    self.assertIn(
                        "Later", [name for _, name in panel.terminals]
                    )
        finally:
            reload_themes()

    async def test_saving_custom_catalog_themes_updates_runtime(self):
        settings = dict(
            theme="dark",
            terminal_theme="inherit",
            leader="C-b",
            status_visible=True,
        )

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
                app.push_screen(ThemePanel())
                await pilot.pause()
                panel = app.screen
                panel.query_one("#terminal-themes", ListView).index = next(
                    index
                    for index, (theme_id, _) in enumerate(panel.terminals)
                    if theme_id == "nord"
                )
                panel.query_one("#ui-themes", ListView).index = next(
                    index
                    for index, (theme_id, _) in enumerate(panel.interfaces)
                    if theme_id == "midnight"
                )
                await pilot.press("ctrl+s")
                await pilot.pause()
                self.assertEqual(settings["terminal_theme"], "nord")
                self.assertEqual(settings["theme"], "midnight")
                self.assertEqual(
                    app.role_colors, cosmos_theme("midnight").palette
                )
                self.assertEqual(app.theme_logo, cosmos_theme("midnight").logo)
                self.assertTrue(app.theme_is_light is False)

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
