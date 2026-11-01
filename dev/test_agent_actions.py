"""Agent Action transport exercises real UI dispatch without altering user settings."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from test_navigation import Probe, snapshot
from cosmos_tui.features.agent.actions import ActionTools
from cosmos_tui.features.assistant.bridge import AgentBridge
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.agent.mcp import ACTION_TOOLS, dispatch


class AgentActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_socket_catalog_ui_menu_and_service_dispatch(self):
        state = snapshot()
        service = [
            dict(id="notifications.toggle", kind="setting", label="Notifications"),
            dict(id="display.open", kind="menu", menu="display", label="Display"),
        ]
        called = []

        async def rpc(method, params=None):
            if method == "actions.list":
                return service
            if method == "actions.invoke":
                called.append(params)
                return dict(applied=True)
            return state if method == "state.snapshot" else state["settings"]

        with patch("cosmos_tui.core.rpc.call", side_effect=rpc):
            app = Probe()
            async with app.run_test(size=(100, 35)) as pilot:
                bridge = AgentBridge(app)
                await bridge.start()
                tools = ActionTools("test")
                option = (
                    f"@cosmos_agent_actions_{app.client} {json.dumps(bridge.path)}\n"
                )
                tools.backend.cli = AsyncMock(return_value=option)
                try:
                    catalog = await tools.list_actions()
                    self.assertEqual(catalog["clients"], [app.client])
                    self.assertIn(
                        "workspace.palette",
                        {row["id"] for row in catalog["ui"]["actions"]},
                    )
                    self.assertEqual(
                        await tools.list_clients(), dict(clients=[app.client])
                    )
                    context = await tools.client_context()
                    self.assertNotIn("actions", context)
                    subset = await tools.list_actions(
                        scope="ui", category="workspace.split"
                    )
                    self.assertEqual(subset["service_actions"], [])
                    self.assertTrue(
                        all(
                            r["id"].startswith("workspace.split")
                            for r in subset["ui"]["actions"]
                        )
                    )
                    import tempfile
                    from pathlib import Path

                    with tempfile.TemporaryDirectory() as directory:
                        target = app.active()
                        metadata = dict(
                            pane_id=target.id,
                            window_id="@0",
                            session_id="$0",
                            session_name="main",
                            pane_current_path=directory,
                            display_id="0:0",
                        )
                        with (
                            patch.object(
                                tools,
                                "resolve_target",
                                AsyncMock(return_value=metadata),
                            ),
                            patch(
                                "cosmos_tui.features.agent.terminal.TerminalTools.pane",
                                AsyncMock(return_value=metadata),
                            ),
                            patch("cosmos_tui.terminal.targets.select", AsyncMock()),
                            patch.object(
                                app.reader_ui, "update_viewer", AsyncMock()
                            ) as opened,
                        ):
                            result = await tools.open_file(directory, "0:0")
                            self.assertEqual(result["view"], "files")
                            self.assertEqual(result["loading"], "pending")
                            self.assertFalse(result["complete"])
                            self.assertEqual(
                                opened.await_args.args[1]["path"], directory
                            )
                            bad = Path(directory) / "unsupported.xyz"
                            bad.write_text("test")
                            with self.assertRaisesRegex(RuntimeError, "unsupported"):
                                await tools.open_file(str(bad), "0:0")
                    from cosmos_tui.features.agent.sessions import WorkspaceTools

                    row = dict(
                        pane_id="%19",
                        window_id="@4",
                        session_id="$7",
                        session_name="task",
                    )
                    with (
                        patch(
                            "cosmos_tui.features.agent.terminal.TerminalTools.pane",
                            AsyncMock(return_value=row),
                        ),
                        patch(
                            "cosmos_tui.terminal.targets.select", AsyncMock()
                        ) as select,
                    ):
                        focused = await tools.ui_call(
                            None, dict(operation="focus", pane="%19")
                        )
                        self.assertEqual(focused["session"], "$7")
                        self.assertEqual(select.await_args.args[1]["pane_id"], "%19")
                    workspace = WorkspaceTools("test")
                    workspace.pane = AsyncMock(return_value=row)
                    with patch.object(
                        ActionTools, "ui_call", AsyncMock(return_value=focused)
                    ) as focus:
                        await workspace.focus_pane("%19", client=app.client)
                        focus.assert_awaited_once_with(
                            app.client, dict(operation="focus", pane="%19")
                        )
                    result = await tools.invoke_action("workspace.palette", "ui")
                    self.assertEqual(result["status"], "dispatched")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, Palette)
                    with self.assertRaisesRegex(RuntimeError, "not available"):
                        await tools.invoke_action("workspace.split_vertical", "ui")
                    await pilot.press("escape")
                    await tools.invoke_action(
                        "display.open", "service", client=app.client
                    )
                    await pilot.pause()
                    self.assertIsInstance(app.screen, Palette)
                    await pilot.press("escape")
                    await tools.invoke_action("notifications.toggle", "service")
                    self.assertEqual(
                        called, [dict(id="notifications.toggle", params={})]
                    )
                    with self.assertRaisesRegex(ValueError, "unknown service"):
                        await tools.invoke_action("missing", "service")
                    tools.backend.cli.return_value = (
                        option
                        + f"@cosmos_agent_actions_other {json.dumps(bridge.path)}\n"
                    )
                    with self.assertRaisesRegex(ValueError, "specify a client"):
                        await tools.invoke_action("workspace.palette", "ui")
                finally:
                    await bridge.close()

    async def test_action_mcp_catalog(self):
        result = await dispatch(None, dict(method="tools/list"), ACTION_TOOLS)
        self.assertEqual(
            {row["name"] for row in result["tools"]},
            {
                "list_actions",
                "invoke_action",
                "list_clients",
                "client_context",
                "open_file",
            },
        )
