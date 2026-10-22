"""Per-client private transport; a disconnect cancels UI without executing a line."""

import asyncio
import json
import os
import socket
import struct
import tempfile
from pathlib import Path
from .assistant import Assistant


class AgentBridge:
    def __init__(self, app):
        self.app = app
        self.directory = tempfile.TemporaryDirectory(prefix="cosmos-agent-ui-")
        self.path = str(Path(self.directory.name) / "ui.sock")
        self.server = None
        self.writers = set()

    async def start(self):
        self.server = await asyncio.start_unix_server(
            self.handle, path=self.path, limit=1024 * 1024
        )
        os.chmod(self.path, 0o600)

    async def handle(self, reader, writer):
        self.writers.add(writer)
        try:
            peer = writer.get_extra_info("socket")
            uid = struct.unpack(
                "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )[1]
            if uid != os.getuid():
                return
            request = json.loads(await asyncio.wait_for(reader.readline(), 3))
            if request.get("version") != 1 or not any(
                p.id == request.get("pane") for p in self.app.panes
            ):
                return
            if self.app.screen is not self.app._workspace_screen:
                writer.write(
                    json.dumps(dict(action="cancel", state=request["state"])).encode()
                    + b"\n"
                )
                await writer.drain()
                return
            future = asyncio.get_running_loop().create_future()

            def done(value):
                if not future.done():
                    future.set_result(value)

            self.app.assistant_passive = None
            screen = Assistant(request)
            self.app.push_screen(screen, done)
            disconnected = asyncio.create_task(reader.read(1))
            try:
                completed, _ = await asyncio.wait(
                    [future, disconnected], return_when=asyncio.FIRST_COMPLETED
                )
                if future in completed:
                    result = future.result()
                    if result["action"] == "edit":
                        self.app.assistant_passive = dict(
                            pane=request["pane"], request=result["state"]["request"]
                        )
                    writer.write(json.dumps(future.result()).encode() + b"\n")
                    await writer.drain()
                elif self.app.screen is screen:
                    await screen.action_cancel()
            finally:
                disconnected.cancel()
                await asyncio.gather(disconnected, return_exceptions=True)
        except (OSError, ValueError, TimeoutError, KeyError):
            pass
        finally:
            self.writers.discard(writer)
            writer.close()
            await writer.wait_closed()

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.writers):
            writer.close()
        self.directory.cleanup()
