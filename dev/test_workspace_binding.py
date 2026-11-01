"""Workspace incarnation is independent of names and inherited ordinary Tmux."""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from cosmos_tui.features.agent.binding import WorkspaceBinding
from cosmos_tui.features.agent.terminal import TerminalTools, FIELDS, FLAGS, NUMBERS
from cosmos_tui.features.agent.configuration import configuration


class BindingTests(unittest.TestCase):
    def test_replacement_and_empty_workspace_reject_old_targets(self):
        binding = WorkspaceBinding("cosmos-fixture")
        identity = binding.validate([dict(pid="99999991")])
        self.assertTrue(identity.startswith("workspace_"))
        self.assertNotIn("cosmos-fixture", identity)
        self.assertEqual(identity, binding.validate([dict(pid="99999991")]))
        with self.assertRaises(ValueError):
            binding.validate([dict(pid="99999992")])
        with self.assertRaises(ValueError):
            binding.validate([])

    def test_launch_identity_and_shell_permission_are_separate(self):
        with patch.dict(
            os.environ,
            COSMOS_WORKSPACE_BINDING=json.dumps(
                dict(name="fixture", identity=["99999991", None])
            ),
        ):
            binding = WorkspaceBinding("fixture")
            with self.assertRaises(ValueError):
                binding.validate([dict(pid="99999992")])
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CONFIG_HOME=directory),
        ):
            config = configuration("private-socket-name", "%4")
            self.assertNotIn(
                "private-socket-name", config["agents"]["cosmos"]["system"]
            )
            self.assertIn(
                dict(action="shell", resource="*", effect="ask"), config["permissions"]
            )


class ToolBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_actions_reject_a_replaced_service_before_dispatch(self):
        from cosmos_tui.features.agent.actions import ActionTools

        tools = ActionTools("fixture")
        tools.panes = AsyncMock(
            side_effect=ValueError("Cosmos workspace service changed")
        )
        with patch(
            "cosmos_tui.features.agent.actions.rpc.call", AsyncMock()
        ) as coordinator:
            with self.assertRaises(ValueError):
                await tools.invoke_action("display.toggle", "service")
            coordinator.assert_not_awaited()

    async def test_real_tool_entry_cannot_rebind_when_metadata_changes(self):
        with patch.dict(os.environ, TMUX="/tmp/ordinary-tmux,1,0"):
            tools = TerminalTools("cosmos-fixture")
        self.assertEqual(tools.backend.argv[1:], ["-L", "cosmos-fixture"])
        row = {k: "1" if k in NUMBERS else "0" if k in FLAGS else "" for k in FIELDS}
        row.update(
            pid="99999991",
            session_id="$1",
            pane_id="%4",
            window_id="@1",
            pane_current_command="bash",
        )
        tools.backend.cli = AsyncMock(return_value="\t".join(row[k] for k in FIELDS))
        self.assertEqual((await tools.workspace_info())["scope"], "cosmos_workspace")
        row["pid"] = "99999992"
        tools.backend.cli.return_value = "\t".join(row[k] for k in FIELDS)
        with self.assertRaisesRegex(ValueError, "service changed"):
            await tools.pane("%4")


if __name__ == "__main__":
    unittest.main()
