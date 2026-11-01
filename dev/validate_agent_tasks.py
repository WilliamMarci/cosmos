"""Real native lifecycle -> local fake provider, including in-flight cancellation."""

import base64
import asyncio
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from unittest.mock import patch

from cosmos_tui.features.agent.launch import environment, runtime
from cosmos_tui.features.agent.profile import configure, initialize_profile
from cosmos_tui.features.agent.tasks.runtime import descriptors, call

entered, aborted = threading.Event(), threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            chunk = dict(
                id="chatcmpl-fixture",
                object="chat.completion.chunk",
                created=1,
                model=body["model"],
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", content="Working"),
                        finish_reason=None,
                    )
                ],
            )
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.flush()
            entered.set()
            for _ in range(200):
                time.sleep(0.05)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            aborted.set()


async def validate(service, descriptor, conversation):
    assert not (await call(descriptor, "status", conversation))["active"]
    assert (
        await call(
            descriptor,
            "wake",
            conversation,
            message="msg_cosmos_fixture1",
            text="Acknowledge without using tools.",
        )
    )["accepted"]
    assert await asyncio.to_thread(entered.wait, 15), "Model provider was not entered"
    assert (await call(descriptor, "status", conversation))["active"]
    result = await call(
        descriptor,
        "wake",
        conversation,
        message="msg_cosmos_fixture2",
        text="Do not run",
    )
    assert result.get("busy"), result
    await call(descriptor, "interrupt", conversation)
    for _ in range(50):
        if not (await call(descriptor, "status", conversation))["active"]:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("Native model turn remained active after interruption")
    assert await asyncio.to_thread(aborted.wait, 5), "HTTP model stream was not aborted"


def main():
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    try:
        with (
            tempfile.TemporaryDirectory(prefix="cosmos-task-native-") as directory,
            patch.dict(
                os.environ,
                XDG_CONFIG_HOME=directory + "/config",
                XDG_RUNTIME_DIR=directory + "/runtime",
                COSMOS_TASKS_HOME=directory + "/tasks",
            ),
        ):
            Path(directory + "/runtime").mkdir(mode=0o700)
            root = initialize_profile()
            (root / "credentials.json").write_text(json.dumps({"deepseek": "fake-key"}))
            configure(base_url=f"http://127.0.0.1:{provider.server_port}/v1")
            (root / "tmp").mkdir(mode=0o700)
            service = "task-native-fixture"
            env = environment(service, "%0")
            env["OPENCODE_DISABLE_MODELS_FETCH"] = "1"
            env["OPENCODE_PASSWORD"] = "fixture-local-only"
            # Choose a free localhost port for the native HTTP session-creation API.
            with socket.socket() as temporary:
                temporary.bind(("127.0.0.1", 0))
                port = temporary.getsockname()[1]
            command, cwd = runtime()
            with open(directory + "/native.log", "w+") as log:
                proc = subprocess.Popen(
                    command + ["serve", "--port", str(port), "--hostname", "127.0.0.1"],
                    cwd=cwd,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                try:
                    conversation = None
                    for _ in range(100):
                        if proc.poll() is not None:
                            break
                        try:
                            request = Request(
                                f"http://127.0.0.1:{port}/api/session",
                                data=json.dumps({"title": "Task fixture"}).encode(),
                                headers={
                                    "Content-Type": "application/json",
                                    "Authorization": "Basic "
                                    + base64.b64encode(
                                        b"opencode:fixture-local-only"
                                    ).decode(),
                                },
                                method="POST",
                            )
                            with urlopen(request, timeout=0.5) as response:
                                data = json.load(response)
                                conversation = data.get("data", data)["id"]
                            break
                        except (OSError, ValueError, KeyError):
                            time.sleep(0.1)
                    if not conversation:
                        log.seek(0)
                        raise AssertionError(log.read()[-4000:])
                    rows = descriptors(service)
                    assert rows, "Native Session lifecycle descriptor missing"
                    asyncio.run(validate(service, rows[0], conversation))
                    from cosmos_tui.features.agent.tasks.storage import Tasks

                    ledger = Tasks(service)
                    ledger.pause(conversation)
                    denied = asyncio.run(
                        call(
                            rows[0],
                            "wake",
                            conversation,
                            message="msg_cosmos_paused",
                            text="Do not resume",
                        )
                    )
                    assert denied.get("paused") and not denied["accepted"]
                    entered.clear()
                    aborted.clear()
                    chat = Request(
                        f"http://127.0.0.1:{port}/api/session/{conversation}/prompt",
                        data=json.dumps(
                            dict(
                                id="msg_cosmos_manual_chat",
                                text="Discuss the plan only; do not operate the paused terminal.",
                            )
                        ).encode(),
                        headers=dict(request.headers),
                        method="POST",
                    )
                    with urlopen(chat, timeout=5) as response:
                        assert response.status == 200
                        json.load(response)
                    assert entered.wait(15), (
                        "Explicit user chat did not reach model while task was paused"
                    )
                    assert ledger.paused(conversation), (
                        "Chat unexpectedly resumed terminal task"
                    )
                    assert asyncio.run(call(rows[0], "status", conversation)).get(
                        "chat_only"
                    ), "Chat was not distinguished from task execution"
                    asyncio.run(call(rows[0], "interrupt", conversation))
                    assert aborted.wait(5), "Chat stream was not aborted"
                    proc.terminate()
                    proc.wait(timeout=5)
                    from cosmos_tui.features.agent.tasks.runtime import ensure

                    replacement = asyncio.run(ensure(service, conversation))
                    try:
                        assert replacement["pid"] != proc.pid
                        assert not asyncio.run(
                            call(replacement, "status", conversation)
                        )["active"]
                    finally:
                        os.kill(replacement["pid"], signal.SIGTERM)
                    print(
                        "PASS: native Session wake/busy/interrupt; actual model HTTP aborted; paused HTTP user chat accepted without restoring control; headless restart reopened saved conversation"
                    )
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
    finally:
        provider.shutdown()
        provider.server_close()


if __name__ == "__main__":
    main()
