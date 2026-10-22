#!/usr/bin/env python3
"""Real Readline regression: repeated Cosmos editing must not append prompts."""

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="cosmos-agent-roundtrip-") as tmp:
    env = dict(
        os.environ,
        XDG_RUNTIME_DIR=tmp,
        XDG_CONFIG_HOME=tmp + "/config",
        XDG_STATE_HOME=tmp + "/state",
        XDG_CACHE_HOME=tmp + "/cache",
        COSMOS_TMUX_SOCKET=f"cosmos-roundtrip-{os.getpid()}",
        TERMINAL_AGENT_DEMO="1",
        COSMOS_GRAPHICS="text",
        TERM="xterm-256color",
        HISTFILE="/dev/null",
    )
    fd, slave = pty.openpty()
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 800, 480))
    original = termios.tcgetattr(slave)
    process = subprocess.Popen(
        [str(ROOT / "dev/cosmos-textual")],
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )

    def pump(seconds=0.2):
        data = b""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.02)[0]:
                data += os.read(fd, 65536)
        return data

    def tmux(*args):
        return subprocess.check_output(
            ["tmux", "-L", env["COSMOS_TMUX_SOCKET"], *args],
            env=env,
            text=True,
            stderr=subprocess.DEVNULL,
        )

    def wait(predicate):
        for _ in range(150):
            pump(0.05)
            try:
                if predicate():
                    return
            except subprocess.CalledProcessError:
                pass
        raise AssertionError("timed out")

    try:
        wait(
            lambda: tmux(
                "show-options", "-pqv", "-t", "main", "@cosmos_terminal_agent"
            ).strip()
            == "1"
        )
        tmux(
            "send-keys",
            "-t",
            "main",
            "PROMPT_COMMAND=_terminal_agent_prompt_cleanup; PS1=$'ROUNDTRIP-PROBE\\n$ '; clear",
            "Enter",
        )
        wait(lambda: "ROUNDTRIP-PROBE" in tmux("capture-pane", "-p", "-t", "main"))
        pump(0.2)
        os.write(fd, b"echo hi")
        pump(0.2)
        for index in range(12):
            os.write(fd, b"\x02a")
            pump(0.35)
            during = tmux("capture-pane", "-p", "-t", "main")
            assert during.count("ROUNDTRIP-PROBE") == 1, ("during", index, during)
            if index == 4:
                fcntl.ioctl(
                    fd, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 92, 920, 560)
                )
                pump(0.25)
            os.write(fd, b"\t" if index % 2 == 0 else b"\x1b")
            pump(0.3)
            screen = tmux("capture-pane", "-p", "-t", "main")
            assert screen.count("ROUNDTRIP-PROBE") == 1, (index, screen)
            assert screen.count("echo hi") == 1, (index, screen)
        os.write(fd, b"\x02a")
        pump(0.35)
        os.write(fd, b"convert\r")
        wait(lambda: "magick" in tmux("capture-pane", "-p", "-t", "main"))
        pump(0.3)
        screen = tmux("capture-pane", "-p", "-t", "main")
        assert screen.count("ROUNDTRIP-PROBE") == 1, ("generate", screen)
        os.write(fd, b"\t")
        pump(0.3)
        # Edit and execute the original draft, proving Readline still owns the line.
        os.write(fd, b'\x15printf "roundtrip-executed:%s\\n" ok\r')
        wait(
            lambda: "roundtrip-executed:ok" in tmux("capture-pane", "-p", "-t", "main")
        )
        os.write(fd, b"\x02d")
        pump(0.3)
        assert process.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        print(
            json.dumps(
                dict(
                    roundtrips=12,
                    prompt_copies=1,
                    draft_copies=1,
                    generation=True,
                    resize=True,
                    execution=True,
                    terminal_restore=True,
                )
            )
        )
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
