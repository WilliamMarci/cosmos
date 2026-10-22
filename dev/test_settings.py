"""Settings behavior: persistence, cycle controls, phases and popup surfaces."""

import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe, snapshot
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.features.navigation.about import About
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.input import keymap
from cosmos_tui.ui.settings import SettingRow
from cosmos_tui.ui.chrome import Frame
from textual.widgets import ListView, ListItem, Input


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_choice_persistence_navigation_and_matching_background(self):
        state = snapshot()
        state["settings"]["viewer_cache_mb"] = 128

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
            async with app.run_test(size=(100, 40)) as pilot:
                app.push_screen(Palette())
                await pilot.pause()
                menu = app.screen
                menu.query_one(ListView).index = next(
                    i for i, r in enumerate(menu.rows) if r["label"] == "Reader"
                )
                await pilot.press("full_stop")
                self.assertEqual(menu.menu, "reader_settings")
                await pilot.press("right")
                self.assertEqual(state["settings"]["viewer_cache_mb"], 256)
                from textual.color import Color

                self.assertEqual(
                    menu.query_one(ListItem).styles.background,
                    Color.parse(app.role_colors["acc"]),
                )
                await pilot.press("left")
                self.assertEqual(state["settings"]["viewer_cache_mb"], 128)
                row = menu.query_one(SettingRow)
                await pilot.click(row, offset=(row.size.width - 1, 0))
                self.assertEqual(state["settings"]["viewer_cache_mb"], 256)
                self.assertEqual(
                    menu.query_one(Frame).styles.background,
                    menu.query_one(ListView).styles.background,
                )
                await pilot.press("comma")
                self.assertEqual(menu.menu, "settings")
                await pilot.press("q")
                self.assertIs(app.screen, app._workspace_screen)
                for cls in (About, ThemePanel):
                    app.push_screen(cls())
                    await pilot.pause()
                    self.assertEqual(app.screen.styles.background.a, 0)
                    self.assertEqual(app.screen.styles.background_tint.a, 0)
                    await pilot.press("escape")

    async def test_binding_hints_and_explicit_stage_fields(self):
        state = snapshot()
        state["settings"]["leader"] = "C-a"
        state["settings"]["keybindings"] = {"workspace.palette": ["leader+x"]}

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
        app.settings = copy.deepcopy(state["settings"])
        with patch("cosmos_tui.core.rpc.call", side_effect=rpc):
            async with app.run_test(size=(100, 40)) as pilot:
                app.push_screen(Palette("keys"))
                await pilot.pause()
                app.screen.query_one(Input).value = "Settings panel"
                await pilot.pause()
                self.assertEqual(app.screen.rows[0]["hint"], "Ctrl+A → x")
                rendered = app.screen.query_one(SettingRow).render()
                self.assertTrue(
                    any(
                        str(span.style) == app.role_colors["mute"]
                        for span in rendered.spans
                    )
                )
                await app.screen.invoke()
                await pilot.pause()
                editor = app.screen
                self.assertIsInstance(editor, KeyBindingEditor)
                self.assertEqual(editor.query_one("#key-value", Input).value, "leader")
                self.assertEqual(editor.query_one("#key-next", Input).value, "x")
                editor.query_one("#key-next", Input).value = "f2"
                await pilot.press("enter")
                self.assertEqual(
                    state["settings"]["keybindings"]["workspace.palette"], ["leader+f2"]
                )
                await pilot.pause()
                self.assertIn("f2", app.screen.rows[0]["hint"])
                command = next(c for c in keymap.COMMANDS if c.id == "global.start")
                app.push_screen(KeyBindingEditor(command))
                await pilot.pause()
                editor = app.screen
                editor.query_one("#key-value", Input).value = ","
                await pilot.pause()
                self.assertEqual(editor.values(), ["comma"])
                await pilot.press("escape")
                unbound = next(c for c in keymap.COMMANDS if c.id == "workspace.new_session")
                app.push_screen(KeyBindingEditor(unbound))
                await pilot.pause()
                self.assertEqual(app.screen.count, 1)
                self.assertEqual(app.screen.query_one("#key-value", Input).value, "")
