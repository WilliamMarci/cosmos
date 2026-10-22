"""Existing coordinator wire contract; no Rust UI implementation is imported."""

import asyncio
import json
import os
from pathlib import Path


def socket_path():
    return os.getenv(
        "COSMOS_CONTROL_SOCKET",
        str(
            Path(os.getenv("XDG_RUNTIME_DIR", f"/tmp/cosmos-{os.getuid()}"))
            / "cosmos/control.sock"
        )
        if os.getenv("XDG_RUNTIME_DIR")
        else f"/tmp/cosmos-{os.getuid()}/control.sock",
    )


async def call(method, params=None):
    async with asyncio.timeout(5):
        reader, writer = await asyncio.open_unix_connection(
            socket_path(), limit=1024 * 1024
        )
        try:
            for i, name, args in [
                (1, "initialize", {"protocol_major": 1}),
                (2, method, params or {}),
            ]:
                writer.write(
                    (
                        json.dumps(
                            {"jsonrpc": "2.0", "id": i, "method": name, "params": args}
                        )
                        + "\n"
                    ).encode()
                )
                await writer.drain()
                response = json.loads(await reader.readline())
                if "error" in response:
                    raise RuntimeError(response["error"].get("message", "RPC error"))
            return response["result"]
        finally:
            writer.close()
            await writer.wait_closed()
