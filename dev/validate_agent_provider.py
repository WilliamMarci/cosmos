"""Real Agent -> native provider -> local fake API. No paid request or user key."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import tempfile
import threading
from unittest.mock import patch

from cosmos_tui.features.agent.profile import configure, initialize_profile
from cosmos_tui.features.agent.launch import environment, runtime

MARKER = "COSMOS_LOCAL_API_OK"
requests = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append((self.path, body.get("model")))
        response = dict(
            id="chatcmpl-fixture",
            object="chat.completion",
            created=1,
            model=body["model"],
            choices=[
                dict(
                    index=0,
                    message=dict(role="assistant", content=MARKER),
                    finish_reason="stop",
                )
            ],
            usage=dict(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        self.send_response(200)
        if body.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in (
                (dict(role="assistant", content=MARKER), None),
                ({}, "stop"),
            ):
                chunk = dict(
                    id="chatcmpl-fixture",
                    object="chat.completion.chunk",
                    created=1,
                    model=body["model"],
                    choices=[dict(index=0, delta=delta, finish_reason=finish)],
                )
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with (
            tempfile.TemporaryDirectory(prefix="cosmos-provider-") as directory,
            patch.dict(os.environ, XDG_CONFIG_HOME=directory + "/config"),
        ):
            root = initialize_profile()
            (root / "credentials.json").write_text(
                json.dumps({"deepseek": "local-fixture-key"})
            )
            configure(base_url=f"http://127.0.0.1:{server.server_port}/v1")
            (root / "tmp").mkdir(mode=0o700)
            env = environment("cosmos-local-provider-test", "%0")
            env["OPENCODE_DISABLE_MODELS_FETCH"] = "1"
            command, cwd = runtime()
            result = subprocess.run(
                command
                + [
                    "run",
                    "--standalone",
                    "--format",
                    "json",
                    "--title",
                    "Local provider fixture",
                    "Reply with a short acknowledgement. Do not use tools.",
                ],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0, result.stderr[-3000:]
            assert MARKER in result.stdout, (
                result.stdout[-3000:],
                result.stderr[-3000:],
            )
            assert ("/v1/chat/completions", "deepseek-flash") in requests, requests
            assert "local-fixture-key" not in result.stdout
            print(
                "PASS: real Agent completed a streamed response through the configured DeepSeek adapter and local API"
            )
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
