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
            app.backend.session = "research"
            app.backend.tabs = [["@3", "2", "1", "bash"], ["@8", "5", "0", "other"]]
            app.backend.request.return_value = ["/tmp/deep/long/path\tbash"]
            await app.status.refresh()
            bar = app.query_one("#status", StatusBar)
            self.assertIn("research·2:1", bar._content.plain)
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
            self.assertIn("research·2:1", bar._content.plain)
            # A sole window keeps its actual index internally even though it is hidden.
            app.backend.tabs = [["@3", "2", "1", "bash"]]
            await app.status.refresh()
            self.assertIn("research·1", bar._content.plain)
            self.assertNotIn("research·2:1", bar._content.plain)
            self.assertEqual((pane.id, pane.window_id), ("%19", "@3"))

    async def test_task_positions_keep_stable_keys_after_renumbering(self):
        from unittest.mock import AsyncMock, patch
        from cosmos_tui.features.agent.tasks.panel import pane_positions

        rows = [dict(pane_id="%19", session_name="work", window_index=2, pane_index=1)]
        with patch("cosmos_tui.features.agent.terminal.TerminalTools.panes", AsyncMock(return_value=rows)):
            self.assertEqual(await pane_positions("test"), {"%19": "work · 2:1"})
            rows[0]["pane_index"] = 0
            self.assertEqual(await pane_positions("test"), {"%19": "work · 2:0"})

    async def test_workspace_positions_resolve_to_original_stable_panes(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from cosmos_tui.features.agent.sessions import WorkspaceTools

        tools = SimpleNamespace(panes=AsyncMock(return_value=[dict(
            session_id="$7", session_name="research", pane_id="%19", window_id="@3",
            window_index=2, pane_index=1, pane_current_command="bash",
        )]))
        sessions = await WorkspaceTools.list_sessions(tools)
        self.assertEqual(sessions[0]["name"], "research")
        self.assertEqual(sessions[0]["panes"][0]["position"], "2:1")
        self.assertEqual(sessions[0]["panes"][0]["pane"], "%19")
