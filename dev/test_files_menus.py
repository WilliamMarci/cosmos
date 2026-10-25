"""File launcher, contextual keyboard help, and categorized Actions."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from textual.widgets import ListView
from test_navigation import Probe, snapshot
from cosmos_tui.features.navigation.menus import StartMenu, ActionDrawer
from cosmos_tui.ui.help import Help
from cosmos_tui.ui.menus import CompactMenu


class FilesMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_launcher_help_and_type_action(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict("os.environ", {"XDG_CACHE_HOME": temp}),
        ):
            root = Path(temp) / "files"
            root.mkdir()
            (root / "folder").mkdir()
            (root / "picture.png").write_bytes(b"fake")
            (root / "script.py").write_text("pass")
            state = snapshot()

            async def rpc(method, params=None):
                return copy.deepcopy(state) if method == "state.snapshot" else []

            with patch("cosmos_tui.core.rpc.call", side_effect=rpc):
                app = Probe()
                async with app.run_test(size=(110, 38)) as pilot:

                    async def backend(command):
                        return [str(root)] if "pane_current_path" in command else []

                    app.backend.request.side_effect = backend
                    app.action_start_menu()
                    await pilot.pause()
                    self.assertIsInstance(app.screen, StartMenu)
                    menu = app.screen
                    menu.query_one(ListView).index = next(
                        i for i, r in enumerate(menu.rows) if r["label"] == "Files"
                    )
                    await pilot.press("enter")
                    await pilot.pause()
                    pane = app.panes[0]
                    self.assertEqual(app.reader_ui.state(pane)["path"], str(root))
                    app.settings["keybindings"] = {"files.hidden": ["z"]}
                    await pilot.press("ctrl+b", "question_mark")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, Help)
                    self.assertEqual(app.screen.heading, "Files")
                    self.assertIn(("z", "Toggle hidden files"), app.screen.items)
                    self.assertFalse(
                        any(label == "Zoom in" for _, label in app.screen.items)
                    )
                    await pilot.press("escape")
                    app.action_context_actions()
                    await pilot.pause()
                    self.assertIsInstance(app.screen, ActionDrawer)
                    menu = app.screen
                    groups = {r.get("group") for r in menu.entries}
                    self.assertTrue(
                        {"Files / Operations", "Files / Sorting", "Files / Filters"}
                        <= groups
                    )
                    menu.query_one(ListView).index = next(
                        i
                        for i, r in enumerate(menu.rows)
                        if r.get("id") == "files.category"
                    )
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, CompactMenu)
                    app.screen.index = 2
                    await pilot.press("enter")
                    await pilot.pause()
                    current = app.reader_ui.state(pane)
                    self.assertEqual(current["category"], "image")
                    self.assertEqual(
                        [i["name"] for i in app.reader_ui.files.listing(current)],
                        ["picture.png"],
                    )
                    await pilot.press("q")
                    app.reader_ui.preview.close()
