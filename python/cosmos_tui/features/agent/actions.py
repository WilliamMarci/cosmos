"""Discover and invoke the existing service/client Action registries."""

import asyncio
import json
import shlex
from pathlib import Path

from cosmos_tui.core import rpc
from cosmos_tui.features.agent.terminal import TerminalTools

PREFIX = "@cosmos_agent_actions_"


class ActionTools(TerminalTools):
    server_name = "cosmos-actions"

    async def clients(self):
        await self.panes()
        text = await self.backend.cli("show-options", "-g")
        result = {}
        for line in text.splitlines():
            parts = shlex.split(line)
            if (
                len(parts) == 2
                and parts[0].startswith(PREFIX)
                and Path(parts[1]).is_socket()
            ):
                result[parts[0][len(PREFIX) :]] = parts[1]
        return result

    async def ui_call(self, client, request):
        clients = await self.clients()
        if client is None:
            if len(clients) != 1:
                raise ValueError(
                    "specify a client from list_clients; no unique connected Cosmos UI"
                )
            client = next(iter(clients))
        if client not in clients:
            raise ValueError("Cosmos UI client is no longer connected")
        async with asyncio.timeout(10):
            reader, writer = await asyncio.open_unix_connection(
                clients[client], limit=1024 * 1024
            )
            try:
                writer.write(
                    (
                        json.dumps(dict(request, type="cosmos.actions", client=client))
                        + "\n"
                    ).encode()
                )
                await writer.drain()
                line = await reader.readline()
                if not line:
                    raise RuntimeError(
                        "Cosmos UI disconnected before acknowledging the action"
                    )
                response = json.loads(line)
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response
            finally:
                writer.close()
                await writer.wait_closed()

    async def list_clients(self):
        return dict(clients=list(await self.clients()))

    async def client_context(self, client=None):
        return await self.ui_call(client, dict(operation="context"))

    async def reader_events(self, request_id, client=None, wait_ms=0):
        event = await self.ui_call(
            client,
            dict(operation="reader_events", request_id=request_id, wait_ms=wait_ms),
        )
        if event.get("data", {}).get("error"):
            event["data"]["error"] = self.redact(event["data"]["error"])
        return event

    async def open_file(self, path, target, client=None):
        row = await self.resolve_target(target)
        return await self.ui_call(
            client, dict(operation="open_file", path=path, pane=row["pane_id"])
        )

    async def list_actions(self, client=None, scope=None, category=None):
        await self.panes()
        if scope not in (None, "service", "ui"):
            raise ValueError("scope must be service or ui")
        if category is not None and (not isinstance(category, str) or not category):
            raise ValueError("category must be a nonempty action ID prefix")
        service = await rpc.call("actions.list") if scope != "ui" else []
        clients = await self.clients()
        result = dict(
            service_actions=[
                dict(row, scope="service", requires_ui=row.get("kind") == "menu")
                for row in service
                if category is None or row["id"].startswith(category)
            ],
            clients=list(clients),
            ui=None,
        )
        if scope != "service" and (client is not None or len(clients) == 1):
            result["ui"] = await self.ui_call(
                client, dict(operation="list", category=category)
            )
        return result

    async def invoke_action(self, id, scope, client=None, params=None):
        await self.panes()
        if (
            not isinstance(id, str)
            or scope not in ("service", "ui")
            or (params is not None and not isinstance(params, dict))
        ):
            raise ValueError("provide an action ID, service/ui scope and object params")
        if scope == "ui":
            return await self.ui_call(
                client, dict(operation="invoke", id=id, params=params or {})
            )
        actions = await rpc.call("actions.list")
        action = next((row for row in actions if row["id"] == id), None)
        if not action:
            raise ValueError("unknown service action; refresh list_actions")
        if action.get("kind") == "menu":
            if params:
                raise ValueError("menu actions do not accept params")
            return await self.ui_call(client, dict(operation="menu", id=id))
        args = dict(params or {})
        if client:
            if client not in await self.clients():
                raise ValueError("unknown UI client")
            args["client"] = client
        result = await rpc.call("actions.invoke", dict(id=id, params=args))
        return dict(scope="service", result=result)
