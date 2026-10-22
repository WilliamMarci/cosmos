from __future__ import annotations

from cosmos_tui.core import rpc
from cosmos_tui.core.controller import Controller


class NotificationController(Controller):
    async def on_notice_toast_action(self, event):
        app = self.app
        event.stop()
        method = (
            "notifications.dismiss"
            if event.action == "__dismiss__"
            else "notifications.act"
        )
        try:
            await rpc.call(
                method,
                {
                    "id": event.notification,
                    "action": event.action,
                    "client": app.client,
                },
            )
        except RuntimeError as error:
            await app.action_error(method, error)
