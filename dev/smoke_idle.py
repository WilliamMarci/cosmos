#!/usr/bin/env python3
"""Count actual terminal writes while the workspace and Switch are idle."""

import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import tempfile
import termios
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="cosmos-idle-") as tmp:
    env = dict(
        os.environ,
        XDG_RUNTIME_DIR=tmp,
        XDG_CONFIG_HOME=tmp + "/config",
        XDG_STATE_HOME=tmp + "/state",
        COSMOS_TMUX_SOCKET=f"cosmos-idle-{os.getpid()}",
        COSMOS_GRAPHICS="text",
        TERM="xterm-256color",
        HISTFILE="/dev/null",
    )
    fd, slave = pty.openpty()
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 640, 384))
    original = termios.tcgetattr(slave)
    process = subprocess.Popen(
        [str(ROOT / "dev/cosmos-textual")],
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )

    def read(seconds):
        data = b""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.03)[0]:
                try:
                    data += os.read(fd, 65536)
                except OSError:
                    break
        return data

    def wait(token):
        data = b""
        for _ in range(160):
            data += read(0.05)
            if token in data:
                return
        raise AssertionError(f"missing {token!r}: {data[-500:]!r}")

    try:
        wait(b"cosmos")
        read(3)
        workspace_data = read(2)
        workspace = len(workspace_data)
        os.write(fd, b"\x02s")
        wait(b"Switch")
        read(0.8)
        switch_data = read(2)
        switch = len(switch_data)
        print(
            json.dumps(
                dict(workspace_idle_bytes_2s=workspace, switch_idle_bytes_2s=switch)
            ),
            flush=True,
        )
        if "--measure" not in sys.argv:
            assert b"\x1b[2J" not in switch_data, "idle switcher clears the screen"
            assert workspace < 1024, f"idle workspace keeps repainting: {workspace}"
            assert switch < 4096, f"idle Switch keeps repainting: {switch}"
        # A quiet preview must still react to actual output in the source pane.
        subprocess.run(
            [
                "tmux",
                "-L",
                env["COSMOS_TMUX_SOCKET"],
                "send-keys",
                "-t",
                "main",
                "clear; printf 'live-preview:%s\\n' updated",
                "Enter",
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        wait(b"live-preview:updated")
        os.write(fd, b"\x1b")
        read(0.3)
        os.write(fd, b"\x02d")
        read(0.3)
        assert process.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        subprocess.run(
            ["tmux", "-L", env["COSMOS_TMUX_SOCKET"], "kill-server"],
            env=env,
            capture_output=True,
        )
        subprocess.run(
            [str(ROOT / "target/release/cosmos"), "stop"], env=env, capture_output=True
        )
        os.close(fd)
        os.close(slave)
