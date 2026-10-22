"""Real UI routing across management, contextual actions, launcher and bottom search."""

import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / p) for p in ("python", "terminal_agent")
]
from cosmos_tui.app import Cosmos  # noqa: E402
from cosmos_tui.terminal.tmux import Pane  # noqa: E402
from cosmos_tui.features.settings.panel import Palette  # noqa: E402
from cosmos_tui.features.settings.keybindings import KeyBindingEditor  # noqa: E402
from cosmos_tui.features.navigation.menus import ActionDrawer, StartMenu  # noqa: E402
from cosmos_tui.features.navigation.about import About  # noqa: E402
from cosmos_tui.features.search.bar import BottomSearch  # noqa: E402


class Probe(Cosmos):
    async def on_mount(self, event):
        event.prevent_default()
        self._workspace_screen = self.screen
        self.panes = [Pane("%0", 0, 0, 80, 23, True, [], "", (0, 0))]
        self.backend.request = AsyncMock(return_value=["bash"])
        self.backend.snapshot = AsyncMock(side_effect=lambda: self.panes)
        self.query_one("#agent-powerline").display = False

    async def on_unmount(self, event):
        event.prevent_default()


def snapshot():
    return dict(
        actions=[
            dict(
                id="display.open",
                category="settings",
                label="Display",
                kind="menu",
                menu="display",
            ),
            dict(
                id="keys.open",
                category="settings",
                label="Keybindings",
                kind="menu",
                menu="keys",
            ),
            dict(
                id="mod.launch.open",
                label="Launch tool",
                kind="mod",
                mod="launch",
                group="Tools",
                surfaces=["start"],
                contexts=["workspace"],
            ),
            dict(
                id="mod.terminal.run",
                label="Terminal action",
                kind="mod",
                mod="terminal",
                surfaces=["actions"],
                contexts=["workspace"],
            ),
            dict(
                id="mod.reader.run",
                label="Reader action",
                kind="mod",
                mod="reader",
                surfaces=["actions"],
                contexts=["viewer"],
            ),
        ],
        mods=[],
        settings=dict(theme="dark", leader="C-b", keybindings={}),
    )


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_management_is_separate_and_context_action_overlays_source_pane(self):
        with patch("cosmos_tui.core.rpc.call", AsyncMock(return_value=snapshot())):
            app = Probe()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.press("ctrl+b", "p")
                self.assertIsInstance(app.screen, Palette)
                self.assertEqual(app.screen.menu, "settings")
                self.assertFalse(
                    any(row.get("kind") in ("local", "mod") for row in app.screen.rows)
                )
                await pilot.press(*"keybindings", "enter")
                self.assertEqual(app.screen.menu, "keys")
                await pilot.press("enter")
                self.assertIsInstance(app.screen, KeyBindingEditor)
                await pilot.press("escape", "escape", "escape")
                self.assertIs(app.screen, app._workspace_screen)
                app.action_context_actions = Mock(wraps=app.action_context_actions)
                await pilot.press("ctrl+p")
                self.assertIsInstance(
                    app.screen,
                    ActionDrawer,
                    repr(
                        (
                            app.action_context_actions.call_count,
                            app.settings,
                            app.prefix,
                        )
                    ),
                )
                self.assertEqual(app.screen.styles.background.a, 0)
                frame = app.screen.query_one("#entry-frame")
                self.assertIn(frame.styles.border_left[0], ("", "none"))
                self.assertIn(frame.styles.border_bottom[0], ("", "none"))
                self.assertEqual(
                    (frame.region.x, frame.region.width, frame.region.bottom),
                    (0, 80, 23),
                )
                self.assertLessEqual(frame.region.height, 23 // 2)
                labels = {row["label"] for row in app.screen.entries}
                self.assertIn("Terminal action", labels)
                self.assertNotIn("Reader action", labels)
                self.assertNotIn("Settings", labels)
                await pilot.press(*"split left", "enter")
                self.assertIs(app.screen, app._workspace_screen)
                self.assertTrue(
                    any(
                        "split-window -t %0 -h" in call.args[0]
                        for call in app.backend.request.await_args_list
                    )
                )

    async def test_status_click_opens_grouped_launcher_and_about(self):
        with patch("cosmos_tui.core.rpc.call", AsyncMock(return_value=snapshot())):
            app = Probe()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.click("#status", offset=(1, 0))
                self.assertIsInstance(app.screen, StartMenu)
                self.assertTrue(
                    any(e.get("group") == "Cosmos" for e in app.screen.entries)
                )
                self.assertTrue(
                    any(e["label"] == "Launch tool" for e in app.screen.entries)
                )
                self.assertFalse(
                    any(e["label"] == "Terminal action" for e in app.screen.entries)
                )
                await pilot.press(*"about", "enter")
                self.assertIsInstance(app.screen, About)

    async def test_pdf_search_uses_bottom_bar_without_resizing_terminal(self):
        with patch("cosmos_tui.core.rpc.call", AsyncMock(return_value=snapshot())):
            app = Probe()
            async with app.run_test(size=(80, 24)) as pilot:
                state = dict(
                    path="/tmp/sample.pdf", page=1, zoom=1, pan=[0, 0], query=""
                )
                app.active().viewer = base64.b64encode(
                    json.dumps(state).encode()
                ).decode()
                app.reader_ui.media.load = Mock(return_value=(None, 1, True))
                terminal = app.query_one("#terminal")
                size = terminal.size
                await pilot.press("slash")
                self.assertIsInstance(app.screen, BottomSearch)
                bar = app.screen.query_one("#content-search")
                self.assertEqual((bar.region.y, bar.region.height), (22, 1))
                await pilot.press(*"needle", "enter")
                self.assertEqual(
                    json.loads(base64.b64decode(app.active().viewer))["query"], "needle"
                )
                self.assertEqual(terminal.size, size)
                await pilot.press("escape")
                self.assertIs(app.screen, app._workspace_screen)
                self.assertTrue(app.active().viewer)


if __name__ == "__main__":
    unittest.main()
