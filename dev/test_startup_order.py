"""Startup transport ordering and cleanup after a failed backend connection."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from cosmos_tui.features.assistant.bridge import AgentBridge
from cosmos_tui.runtime.coordinator import RuntimeController


class StartupTests(IsolatedAsyncioTestCase):
    async def test_backend_connects_before_action_registration(self):
        steps = []

        async def connect():
            steps.append("connect")
            return False

        async def start():
            self.assertEqual(steps, ["connect"])
            steps.append("register")

        app = SimpleNamespace(
            screen=object(),
            backend=SimpleNamespace(connect=connect),
            assistant_ui=SimpleNamespace(start=start),
            client="startup-test",
            size=SimpleNamespace(width=80, height=24),
            query_one=Mock(),
            set_interval=Mock(),
            tick=AsyncMock(),
        )
        with (
            patch("cosmos_tui.runtime.coordinator.reload_themes"),
            patch("cosmos_tui.runtime.coordinator.rpc.call", AsyncMock()),
            patch.object(RuntimeController, "tick", AsyncMock()),
        ):
            await RuntimeController(app).on_mount()
        self.assertEqual(steps, ["connect", "register"])

    async def test_bridge_cleanup_without_connected_backend(self):
        app = SimpleNamespace(
            backend=SimpleNamespace(
                request=AsyncMock(side_effect=EOFError("not connected"))
            ),
            client="startup-test",
        )
        bridge = AgentBridge(app)
        directory = bridge.directory.name
        await bridge.close()
        from pathlib import Path

        self.assertFalse(Path(directory).exists())
