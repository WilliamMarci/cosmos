from __future__ import annotations

from cosmos_tui.core import rpc
from cosmos_tui.core.controller import Controller


class NotificationController(Controller):
    @property
    def agent_notices(self):
        if not hasattr(self, "_agent_notices"):
            from cosmos_tui.features.notifications.agent import AgentNotices

            self._agent_notices = AgentNotices(self.app)
        return self._agent_notices

    async def on_notice_toast_action(self, event):
        app = self.app
        event.stop()
        method = (
            "notifications.dismiss"
            if event.action == "__dismiss__"
            else "notifications.act"
        )
        try:
            if event.action != "__dismiss__":
                notices = await rpc.call("notifications.list", {"client": app.client})
                notice = next((n for n in notices if n["id"] == event.notification), None)
                if notice and await self.agent_notices.action(notice, event.action):
                    return
            await rpc.call(
                method,
                {
                    "id": event.notification,
                    "action": event.action,
                    "client": app.client,
                },
            )
        except (OSError, RuntimeError, ValueError, TimeoutError) as error:
            await app.action_error(method, error)
