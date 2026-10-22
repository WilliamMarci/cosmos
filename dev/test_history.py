"""Real Tmux copy-mode display, selection and search through Cosmos key routing."""

import asyncio
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / p) for p in ("python", "terminal_agent")
]
from cosmos_tui.app import Cosmos  # noqa: E402
from cosmos_tui.terminal.tmux import Tmux  # noqa: E402
from cosmos_tui.features.history.selection import selection_range  # noqa: E402
from cosmos_tui.features.search.bar import BottomSearch  # noqa: E402


@unittest.skipUnless(
    os.getenv("COSMOS_TEST_TMUX") == "1", "requires an isolated local Tmux socket"
)
class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_scroll_search_and_copy_real_retained_output(self):
        with patch.dict(
            os.environ, {"COSMOS_TMUX_SOCKET": f"cosmos-history-test-{os.getpid()}"}
        ):
            backend = Tmux("history")
            await backend.cli(
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-s",
                "history",
                "bash --noprofile --norc -i",
            )
            try:
                await backend.connect()
                await backend.send(
                    "text",
                    "for i in $(seq -w 1 120); do printf 'ROW-%s\\n' \"$i\"; done",
                )
                await backend.send("enter")
                await asyncio.sleep(0.2)

                class Probe(Cosmos):
                    async def on_mount(self, event):
                        event.prevent_default()
                        self._workspace_screen = self.screen
                        self.backend = backend
                        self.panes = await backend.snapshot()
                        self.query_one("#agent-powerline").display = False

                    async def on_unmount(self, event):
                        event.prevent_default()

                app = Probe("history")
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.press("ctrl+b", "left_square_bracket")
                    self.assertTrue(app.active().copy_mode)
                    await pilot.press("home")
                    self.assertTrue(any("ROW-001" in row for row in app.active().lines))
                    await pilot.press("slash")
                    self.assertIsInstance(app.screen, BottomSearch)
                    await pilot.press(*"ROW-020", "enter")
                    await pilot.pause()
                    self.assertTrue(any("ROW-020" in row for row in app.active().lines))
                    self.assertEqual(
                        app.screen.query_one("#content-search").region.height, 1
                    )
                    await pilot.press("escape")
                    # Select exactly the matched line using the public key registry.
                    await pilot.press("0", "space", "dollar_sign")
                    self.assertIsNotNone(
                        selection_range(app.active(), app.active().cursor[1])
                    )
                    await pilot.press("y")
                    self.assertFalse(app.active().copy_mode)
                    copied = await backend.cli("show-buffer")
                    self.assertIn("ROW-020", copied)
                    await pilot.press(
                        "ctrl+b", "left_square_bracket", "pageup", "escape"
                    )
                    self.assertFalse(app.active().copy_mode)
                    await pilot.press("ctrl+b", "right_square_bracket")
                    output = await backend.cli("capture-pane", "-p", "-t", "history")
                    self.assertIn("ROW-020", output)
            finally:
                await backend.close()
                await backend.cli("kill-server")


if __name__ == "__main__":
    unittest.main()
