import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cosmos_tui.features.notifications.agent import AgentNotices, PREFIX
from cosmos_tui.features.notifications.controller import NotificationController


class AgentNotificationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = SimpleNamespace(backend=SimpleNamespace(argv=["tmux", "-L", "test"]), client="ui", notification_events=SimpleNamespace(publish=AsyncMock()), action_error=AsyncMock())
        self.bridge = AgentNotices(self.app)
        self.descriptor = dict(id="runtime", pane="%7")
        self.request = dict(id="per_1", sessionID="ses_agent", action="shell", canAlways=True)
        self.notice = dict(id=8, source=PREFIX + "runtime:per_1", resolved=False)

    async def test_publish_once_choices_and_expired_cleanup(self):
        with patch("cosmos_tui.features.notifications.agent.runtime.descriptors", return_value=[self.descriptor]), patch("cosmos_tui.features.notifications.agent.runtime.call", AsyncMock(return_value=[self.request])), patch("cosmos_tui.features.notifications.agent.rpc.call", AsyncMock(return_value=[])):
            await self.bridge.refresh()
            args = self.app.notification_events.publish.call_args.kwargs
            self.assertEqual([a["label"] for a in args["actions"]], ["✓", "∞", "−"])
            self.request["canAlways"] = False
            await self.bridge.refresh()
            self.assertEqual([a["id"] for a in self.app.notification_events.publish.call_args.kwargs["actions"]], ["once", "reject"])
        self.app.notification_events.publish.reset_mock()
        with patch("cosmos_tui.features.notifications.agent.runtime.descriptors", return_value=[self.descriptor]), patch("cosmos_tui.features.notifications.agent.runtime.call", AsyncMock(return_value=[self.request])), patch("cosmos_tui.features.notifications.agent.rpc.call", AsyncMock(return_value=[self.notice])):
            await self.bridge.refresh()
            self.app.notification_events.publish.assert_not_awaited()
        with patch("cosmos_tui.features.notifications.agent.runtime.descriptors", return_value=[]), patch("cosmos_tui.features.notifications.agent.rpc.call", AsyncMock(return_value=[self.notice])) as rpc:
            await self.bridge.refresh()
            rpc.assert_any_await("notifications.resolve", {"id": 8})

    async def test_open_does_not_approve_and_reply_uses_current_native_session(self):
        with patch("cosmos_tui.features.notifications.agent.runtime.descriptors", return_value=[self.descriptor]), patch.object(self.bridge, "focus", AsyncMock()) as focus, patch("cosmos_tui.features.notifications.agent.runtime.call", AsyncMock(side_effect=[[self.request], dict(replied=True)])) as call, patch("cosmos_tui.features.notifications.agent.rpc.call", AsyncMock()) as rpc:
            self.assertTrue(await self.bridge.action(self.notice, "__open__"))
            focus.assert_awaited_once_with("%7")
            call.assert_not_awaited()
            self.assertTrue(await self.bridge.action(self.notice, "once"))
            call.assert_any_await(self.descriptor, "permission", "ses_agent", request_id="per_1", decision="once")
            rpc.assert_awaited_once_with("notifications.resolve", {"id": 8})

    async def test_dismiss_never_replies_to_permission(self):
        controller = NotificationController(self.app)
        event = SimpleNamespace(action="__dismiss__", notification=8, stop=lambda: None)
        with patch("cosmos_tui.features.notifications.controller.rpc.call", AsyncMock()) as rpc:
            await controller.on_notice_toast_action(event)
            rpc.assert_awaited_once_with("notifications.dismiss", dict(id=8, action="__dismiss__", client="ui"))

    async def test_stale_request_is_not_approved(self):
        with patch("cosmos_tui.features.notifications.agent.runtime.descriptors", return_value=[self.descriptor]), patch("cosmos_tui.features.notifications.agent.runtime.call", AsyncMock(return_value=[])) as call, patch("cosmos_tui.features.notifications.agent.rpc.call", AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "expired"):
                await self.bridge.action(self.notice, "once")
            self.assertEqual(call.await_count, 1)

    async def test_agent_can_send_bounded_completion_message_for_own_window(self):
        from cosmos_tui.features.agent.tasks.tools import TaskTools
        tools = SimpleNamespace(redact=lambda value: value)
        with patch.dict("os.environ", {"TMUX_PANE": "%7"}), patch("cosmos_tui.core.services.NotificationEvents.publish", AsyncMock(return_value={"id": 9})) as publish:
            result = await TaskTools.notify(tools, "Tests passed; task complete")
            self.assertEqual(result, {"id": 9})
            publish.assert_awaited_once_with("Tests passed; task complete", source="agent-message:%7", persistent=True)
            with self.assertRaises(ValueError):
                await TaskTools.notify(tools, "invalid\nmessage")
