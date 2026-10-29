"""Service-isolated real TUI operation and MCP protocol regressions."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid

from cosmos_tui.features.agent.sessions import WorkspaceTools as TerminalTools


@unittest.skipUnless(
    shutil.which("tmux") and shutil.which("vim"), "requires tmux and vim"
)
class AgentTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.socket = "cosmos-agent-test-" + uuid.uuid4().hex
        self.tools = TerminalTools(self.socket)
        self.path = Path(self.directory.name) / "sample.txt"
        self.path.write_text("\n".join(f"row {i:03}" for i in range(120)) + "\n")
        import shlex

        await self.tools.backend.cli(
            "-f",
            "/dev/null",
            "new-session",
            "-d",
            "-x",
            "80",
            "-y",
            "24",
            "-s",
            "test",
            "-c",
            self.directory.name,
            shlex.join([shutil.which("vim"), "-u", "NONE", "-n", str(self.path)]),
        )
        self.pane = (await self.tools.panes())[0]["pane_id"]
        for _ in range(40):
            screen = await self.tools.read_screen(self.pane, wait_ms=50)
            if "row 000" in screen["text"]:
                break
        self.assertIn("row 000", screen["text"])

    async def asyncTearDown(self):
        await self.tools.backend.cli("kill-server")
        self.directory.cleanup()

    async def test_real_vim_read_keys_unicode_paste_and_page(self):
        await self.tools.send_keys(self.pane, ["i"])
        result = await self.tools.send_text(self.pane, "Cosmos 中文 ")
        self.assertFalse(result["return_sent"])
        await self.tools.send_keys(self.pane, ["Escape"])
        screen = await self.tools.read_screen(self.pane, wait_ms=100)
        self.assertIn("Cosmos 中文 row 000", screen["text"])
        await self.tools.send_keys(self.pane, ["G"])
        screen = await self.tools.read_screen(self.pane, wait_ms=100)
        self.assertIn("row 119", screen["text"])
        await self.tools.send_keys(self.pane, ["g", "g", "C-f"])
        screen = await self.tools.read_screen(self.pane, wait_ms=100)
        self.assertNotIn("row 000", screen["text"])
        self.assertTrue(screen["alternate_on"])
        with self.assertRaises(ValueError):
            await self.tools.send_keys(self.pane, ["-t", "%999"])
        with self.assertRaises(ValueError):
            await self.tools.read_screen("%9999999")
        with self.assertRaises(ValueError):
            await self.tools.send_text(self.pane, "\x1b[2J")

    async def test_mouse_and_background_terminal(self):
        await self.tools.send_keys(self.pane, [":"])
        await self.tools.send_text(self.pane, "set mouse=a ttymouse=sgr")
        await self.tools.send_keys(self.pane, ["Enter"])
        await self.tools.read_screen(self.pane, wait_ms=100)
        await self.tools.mouse(self.pane, 4, 5)
        screen = await self.tools.read_screen(self.pane, wait_ms=100)
        self.assertEqual(screen["cursor_y"], 4)
        await self.tools.mouse(self.pane, 4, 5, button="wheel_down")
        screen = await self.tools.read_screen(self.pane, wait_ms=100)
        self.assertNotIn("row 000", screen["text"])
        self.tools.backend.shell_command = lambda: "bash --noprofile --norc"
        created = await self.tools.create_terminal(self.pane)
        self.assertNotEqual(created["pane_id"], self.pane)
        self.assertEqual(created["session_id"], screen["session_id"])
        self.assertEqual(created["pane_current_path"], self.directory.name)

    async def test_session_management_and_private_history_export(self):
        from unittest.mock import patch

        self.tools.backend.shell_command = lambda: "bash --noprofile --norc"
        created = await self.tools.create_session("agent-task", self.pane)
        sid, pane = created["session_id"], created["pane_id"]
        await self.tools.rename_target(sid, "renamed-task")
        await self.tools.rename_target(created["window_id"], "work")
        await self.tools.rename_target(pane, "agent-shell")
        sessions = await self.tools.list_sessions()
        self.assertIn("renamed-task", {s["name"] for s in sessions})
        await self.tools.send_text(pane, "echo COSMOS_HISTORY_FIXTURE")
        await self.tools.send_keys(pane, ["Enter"])
        await self.tools.read_screen(pane, wait_ms=100)
        with patch.dict(os.environ, XDG_CONFIG_HOME=self.directory.name):
            exported = await self.tools.export_history(sid)
        path = Path(exported["path"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertIn("COSMOS_HISTORY_FIXTURE", path.read_text())
        self.assertEqual(json.loads(path.read_text())["session"], sid)
        with self.assertRaises(ValueError):
            await self.tools.rename_target("$999999", "missing")

    async def test_observation_layers_and_private_pane(self):
        result = await self.tools.observe(
            self.pane, ["text", "presentation", "controls"]
        )
        self.assertFalse(result["capabilities"]["image"])
        self.assertIn("row 000", str(result["text"]))
        self.assertIn("presentation", result)
        unchanged = await self.tools.observe(self.pane, since=result["snapshot_id"])
        self.assertTrue(unchanged["unchanged"])
        session_id = (await self.tools.pane(self.pane))["session_id"]
        await self.tools.backend.cli(
            "set-option", "-p", "-t", self.pane, "@cosmos_private", "1"
        )
        for operation in (
            self.tools.observe(self.pane),
            self.tools.read_screen(self.pane),
            self.tools.send_text(self.pane, "must not send"),
            self.tools.export_history(session_id),
        ):
            with self.assertRaises((PermissionError, ValueError)):
                await operation
        rows = await self.tools.panes()
        self.assertTrue(rows[0]["private"])
        self.assertEqual(rows[0]["pane_current_path"], "")

    async def test_stdio_discovery_and_tool_call(self):
        env = dict(
            os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "python")
        )
        messages = [
            dict(jsonrpc="2.0", id=1, method="initialize", params={}),
            dict(jsonrpc="2.0", method="notifications/initialized"),
            dict(jsonrpc="2.0", id=2, method="tools/list"),
            dict(
                jsonrpc="2.0",
                id=3,
                method="tools/call",
                params=dict(name="read_screen", arguments=dict(pane=self.pane)),
            ),
            dict(
                jsonrpc="2.0",
                id=4,
                method="tools/call",
                params=dict(
                    name="send_keys", arguments=dict(pane=self.pane, keys=["-t"])
                ),
            ),
        ]
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "cosmos_tui.features.agent",
            "mcp",
            "--socket",
            self.socket,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        out, err = await process.communicate(
            "".join(json.dumps(m) + "\n" for m in messages).encode()
        )
        self.assertEqual(process.returncode, 0, err)
        replies = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(len(replies), 4)
        self.assertEqual(len(replies[1]["result"]["tools"]), 12)
        self.assertIn("row 000", replies[2]["result"]["content"][0]["text"])
        self.assertTrue(replies[3]["result"]["isError"])


class RuntimeSelectionTests(unittest.TestCase):
    def test_package_without_vendor_uses_bundle_or_system(self):
        from unittest.mock import patch
        from cosmos_tui.features.agent.launch import runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin/cosmos-agent"
            binary.parent.mkdir()
            binary.write_text("#!/bin/sh\n")
            binary.chmod(0o755)
            with (
                patch("cosmos_tui.features.agent.launch.PROJECT_ROOT", root),
                patch(
                    "cosmos_tui.features.agent.launch.shutil.which",
                    return_value="/usr/bin/opencode",
                ),
                patch.dict(os.environ, COSMOS_AGENT_RUNTIME="auto", COSMOS_OPENCODE=""),
            ):
                self.assertEqual(runtime(), ([str(binary)], None))
                binary.unlink()
                self.assertEqual(runtime(), (["/usr/bin/opencode"], None))
                os.environ["COSMOS_AGENT_RUNTIME"] = "bundled"
                with self.assertRaisesRegex(RuntimeError, "Bundled"):
                    runtime()


if __name__ == "__main__":
    unittest.main()
