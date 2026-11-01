"""Authenticated native Session API transport; never enters text into an Agent pane."""

import hashlib
import asyncio
import json
import os
from pathlib import Path
import stat
import subprocess

from cosmos_tui.features.agent.control import location
from cosmos_tui.features.agent.profile import private_directory


def registry(socket):
    directory = location(socket).with_suffix(".runtimes")
    if len(os.fsencode(directory)) + 23 > 103:
        root = private_directory(Path(f"/tmp/cosmos-{os.getuid()}"))
        directory = root / ("tasks-" + hashlib.sha256(socket.encode()).hexdigest()[:16])
    return private_directory(directory)


def descriptors(socket):
    result = []
    for path in registry(socket).glob("*.json"):
        try:
            info = path.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                continue
            row = json.loads(path.read_text())
            sock = Path(row["socket"])
            if (
                sock.parent != path.parent
                or not sock.is_socket()
                or sock.stat().st_uid != os.getuid()
            ):
                continue
            result.append(row)
        except (OSError, ValueError, KeyError):
            continue
    return result


async def call(descriptor, operation, conversation, **args):
    async with asyncio.timeout(4):
        reader, writer = await asyncio.open_unix_connection(
            descriptor["socket"], limit=131072
        )
        try:
            writer.write(
                (
                    json.dumps(
                        dict(
                            auth=descriptor["key"],
                            operation=operation,
                            session=conversation,
                            **args,
                        )
                    )
                    + "\n"
                ).encode()
            )
            await writer.drain()
            data = json.loads(await reader.readline())
            if "error" in data:
                raise RuntimeError(data["error"])
            return data["result"]
        finally:
            writer.close()
            await writer.wait_closed()


async def find(socket, conversation, preferred=None):
    rows = sorted(descriptors(socket), key=lambda d: d["id"] != preferred)
    for row in rows:
        try:
            await call(row, "status", conversation)
            return row
        except (OSError, RuntimeError, ValueError, TimeoutError):
            continue
    return None


def launch_headless(socket):
    from cosmos_tui.features.agent.launch import runtime, native_runtime, environment
    from cosmos_tui.features.agent.profile import initialize_profile

    command, cwd = runtime()
    if not native_runtime(command, cwd):
        raise RuntimeError(
            "Scheduled tasks require native Cosmos Agent; plain OpenCode is not integrated"
        )
    initialize_profile()
    env = environment(socket, "")
    import secrets

    env["OPENCODE_PASSWORD"] = secrets.token_hex(32)  # HTTP is not the task transport.
    env["OPENCODE_DISABLE_MODELS_FETCH"] = "1"
    from cosmos_tui.features.agent.tasks.storage import Tasks

    path = Tasks(socket).path.with_suffix(".native.log")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        process = subprocess.Popen(
            command + ["serve", "--port", "0", "--hostname", "127.0.0.1"],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=fd,
            stderr=fd,
            start_new_session=True,
        )
        import threading

        threading.Thread(target=process.wait, daemon=True).start()
    finally:
        os.close(fd)


async def ensure(socket, conversation, preferred=None):
    target = await find(socket, conversation, preferred)
    if target:
        return target
    # The scheduler holds the per-service worker lock; only it starts a replacement.
    await asyncio.to_thread(launch_headless, socket)
    for _ in range(60):
        await asyncio.sleep(0.1)
        target = await find(socket, conversation, preferred)
        if target:
            return target
    raise RuntimeError("Native Agent runtime unavailable; inspect the private task log")
