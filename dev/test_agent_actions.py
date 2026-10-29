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
            {row["name"] for row in result["tools"]}, {"list_actions", "invoke_action"}
        )
