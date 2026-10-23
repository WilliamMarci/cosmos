"""Missing-session attach publishes one session-scoped creation notice."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "python")]

from cosmos_tui.core.services import NotificationEvents  # noqa: E402
from cosmos_tui.runtime.coordinator import notify_session_created  # noqa: E402


class AttachNotificationTests(unittest.IsolatedAsyncioTestCase):
    def app(self):
        app = SimpleNamespace(
            backend=SimpleNamespace(session="research", session_id="$3", created=True)
        )
        app.notification_events = NotificationEvents(app)
        return app

    async def test_only_new_sessions_notify(self):
        app = self.app()
        calls = []

        async def call(method, params=None):
            calls.append((method, params))
            return {}

        with patch("cosmos_tui.core.rpc.call", side_effect=call):
            await notify_session_created(app, False)
            self.assertEqual(calls, [])
            await notify_session_created(app, True)
        self.assertEqual(len(calls), 1)
        method, params = calls[0]
        self.assertEqual(method, "notifications.publish")
        self.assertEqual(params["text"], "Session 'research' not found; created")
        self.assertEqual(params["source"], "workspace")
        self.assertEqual(params["level"], "info")
        self.assertEqual(params["session_id"], "$3")

    async def test_failed_publication_does_not_block_attach(self):
        app = self.app()
        with (
            patch(
                "cosmos_tui.core.rpc.call",
                side_effect=RuntimeError("coordinator unavailable"),
            ),
            self.assertLogs(
                "cosmos_tui.runtime.coordinator", level="WARNING"
            ) as captured,
        ):
            await notify_session_created(app, True)
        self.assertIn("could not publish", captured.output[0])


if __name__ == "__main__":
    unittest.main()
