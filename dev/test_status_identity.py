"""Status target identity and absolute copy-mode cursor progress."""

import unittest
from test_navigation import Probe
from cosmos_tui.features.status.bar import StatusBar
from cosmos_tui.terminal.tmux import Pane


class IdentityStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_position_indices_and_history_progress_reserve_space(self):
        app = Probe()
        async with app.run_test(size=(100, 30)):
            pane = Pane(
                "%19",
                0,
                0,
                100,
                24,
                True,
                [],
                "",
                (5, 3),
                session_id="$7",
                window_id="@3",
                index=1,
                copy_mode=True,
                history_size=100,
                scroll_position=50,
            )
            app.panes = [pane]
            app.backend.tabs = [["@3", "2", "1", "bash"]]
            app.backend.request.return_value = ["/tmp/deep/long/path\tbash"]
            await app.status.refresh()
            bar = app.query_one("#status", StatusBar)
            self.assertIn("2:1", bar._content.plain)
            self.assertNotIn("7:19", bar._content.plain)
            start = bar._content.plain.index("2:1")
            self.assertNotEqual(
                bar._content.get_style_at_offset(app.console, start).color,
                bar._content.get_style_at_offset(app.console, start + 2).color,
            )
            self.assertIn("COPY 54/124:6 44%", bar._content.plain)
            pane.copy_mode = False
            await app.status.refresh()
            self.assertNotIn("COPY", bar._content.plain)
            self.assertIn("2:1", bar._content.plain)

    async def test_task_positions_keep_stable_keys_after_renumbering(self):
        from unittest.mock import AsyncMock, patch
        from cosmos_tui.features.agent.tasks.panel import pane_positions

        rows = [dict(pane_id="%19", session_name="work", window_index=2, pane_index=1)]
        with patch("cosmos_tui.features.agent.terminal.TerminalTools.panes", AsyncMock(return_value=rows)):
            self.assertEqual(await pane_positions("test"), {"%19": "work · 2:1"})
            rows[0]["pane_index"] = 0
            self.assertEqual(await pane_positions("test"), {"%19": "work · 2:0"})
