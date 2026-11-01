"""Native Agent permission notices; replies use the authenticated lifecycle bridge."""

import asyncio
import time

from cosmos_tui.core import rpc
from cosmos_tui.features.agent.tasks import runtime
from cosmos_tui.features.agent.terminal import TerminalTools
from cosmos_tui.terminal.targets import select

PREFIX = "agent-permission:"
MESSAGE = "agent-message:"


class AgentNotices:
    def __init__(self, app):
        self.app = app
        self.next_poll = 0
        self.worker = None

    def poll(self):
        if time.monotonic() < self.next_poll or (self.worker and not self.worker.done()):
            return
        self.next_poll = time.monotonic() + 1
        self.worker = asyncio.create_task(self.refresh())

    async def refresh(self):
        try:
            socket = self.app.backend.argv[2]
            descriptors = runtime.descriptors(socket)
            results = await asyncio.gather(
                *(runtime.call(d, "pending", "ses_notifications") for d in descriptors),
                return_exceptions=True,
            )
            notices = await rpc.call("notifications.list", {"client": self.app.client})
            known = {n["source"] for n in notices}
            live, unavailable = set(), set()
            for descriptor, result in zip(descriptors, results):
                if isinstance(result, BaseException):
                    unavailable.add(descriptor["id"])
                    continue
                for request in result:
                    source = PREFIX + descriptor["id"] + ":" + request["id"]
                    live.add(source)
                    if source in known:
                        continue
                    actions = [dict(id="once", label="✓")]
                    if request.get("canAlways"):
                        actions.append(dict(id="always", label="∞"))
                    actions.append(dict(id="reject", label="−"))
                    # Only a redacted, bounded permission scope; never script source.
                    action = "".join(c for c in request["action"] if c.isprintable())[:80]
                    scope = TerminalTools.redact(" · ".join(str(r) for r in request.get("resources", [])))
                    scope = "".join(c for c in scope if c.isprintable())[:120]
                    await self.app.notification_events.publish(
                        "Agent · " + action + (" · " + scope if scope else " · approval required"),
                        source=source, level="warning", actions=actions, persistent=True,
                    )
            for notice in notices:
                source = notice["source"]
                if source.startswith(PREFIX) and not notice.get("resolved") and source not in live:
                    if source.split(":")[1] not in unavailable:
                        await rpc.call("notifications.resolve", {"id": notice["id"]})
        except (OSError, RuntimeError, ValueError, KeyError, TimeoutError):
            # A disconnected runtime must never turn into approval or block UI refresh.
            return

    async def focus(self, pane):
        tools = TerminalTools(self.app.backend.argv[2])
        row = next((r for r in await tools.panes() if r["pane_id"] == pane), None)
        if not row:
            raise RuntimeError("Agent window is no longer available")
        await select(self.app.backend, dict(row, kind="pane", session=row["session_name"]))

    async def action(self, notice, action):
        source = notice.get("source", "")
        if source.startswith(MESSAGE):
            if action == "__open__":
                await self.focus(source.removeprefix(MESSAGE))
                return True
            return False
        if not source.startswith(PREFIX):
            return False
        _, ident, request_id = source.split(":", 2)
        descriptor = next((d for d in runtime.descriptors(self.app.backend.argv[2]) if d["id"] == ident), None)
        if not descriptor:
            raise RuntimeError("Agent runtime is no longer available")
        if action == "__open__":
            await self.focus(descriptor.get("pane", ""))
            return True
        if action not in ("once", "always", "reject") or notice.get("resolved"):
            raise RuntimeError("Permission request is no longer available")
        pending = await runtime.call(descriptor, "pending", "ses_notifications")
        request = next((r for r in pending if r["id"] == request_id), None)
        if not request:
            await rpc.call("notifications.resolve", {"id": notice["id"]})
            raise RuntimeError("Permission request expired")
        result = await runtime.call(
            descriptor, "permission", request["sessionID"], request_id=request_id, decision=action,
        )
        if result.get("stale"):
            raise RuntimeError("Permission request expired")
        await rpc.call("notifications.resolve", {"id": notice["id"]})
        return True
