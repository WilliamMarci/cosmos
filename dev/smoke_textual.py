#!/usr/bin/env python3
"""Migration gate: Textual owns grid, overlays, graphics batches and terminal cleanup."""

import base64
import fcntl
import json
import os
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time
from pathlib import Path
from viewer_fixtures import png, pdf

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "target/release/cosmos"
with tempfile.TemporaryDirectory(prefix="cosmos-textual-") as tmp:
    tmp = Path(tmp)
    png(tmp / "image.png")
    pdf(tmp / "document.pdf")
    fake_agent = tmp / "fake-opencode"
    fake_agent.write_text("#!/bin/sh\nprintf 'opencode-interface\\n'\nexec sleep 60\n")
    fake_agent.chmod(0o700)
    env = dict(
        os.environ,
        XDG_RUNTIME_DIR=str(tmp),
        XDG_CONFIG_HOME=str(tmp / "config"),
        XDG_STATE_HOME=str(tmp / "state"),
        XDG_CACHE_HOME=str(tmp / "cache"),
        COSMOS_TMUX_SOCKET=f"cosmos-textual-{os.getpid()}",
        COSMOS_GRAPHICS="kitty",
        TERMINAL_AGENT_DEMO="1",
        COSMOS_OPENCODE=str(fake_agent),
        TERM="xterm-kitty",
        HISTFILE="/dev/null",
        TEXTUAL_ANIMATIONS="none",
    )
    clients = []
    handles = []
    all_bytes = bytearray()

    def tmux(*args):
        return subprocess.run(
            ["tmux", "-L", env["COSMOS_TMUX_SOCKET"], *args],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def pump(fd, seconds=0.3):
        data = b""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([fd], [], [], 0.03)[0]:
                try:
                    data += os.read(fd, 65536)
                except OSError:
                    break
        all_bytes.extend(data)
        return data

    def wait(fd, token, timeout=12):
        data = b""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            data += pump(fd, 0.05)
            if token in data:
                return data
        raise AssertionError(f"missing {token!r}: {data[-1500:]!r}")

    def until(fd, condition, timeout=8):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            pump(fd, 0.05)
            if condition():
                return
        raise AssertionError("condition timed out")

    def launch():
        fd, slave = pty.openpty()
        handles.extend([fd, slave])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 640, 384))
        original = termios.tcgetattr(slave)
        p = subprocess.Popen(
            [str(ROOT / "dev/cosmos-textual")],
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
        )
        clients.append(p)
        wait(fd, b"bash")
        pump(fd, 1)
        return p, fd, slave, original

    try:
        p, fd, slave, original = launch()
        assert (
            tmux("display-message", "-p", "-t", "main", "#{pane_height}").strip()
            == "23"
        ), "status must not obscure an application row"
        until(
            fd,
            lambda: tmux(
                "show-options", "-pqv", "-t", "main", "@cosmos_terminal_agent"
            ).strip()
            == "1",
        )
        assert b"\x1b[?25h" in all_bytes, "workspace must show its hardware cursor"
        assert b"\x1b[1 q" in all_bytes, "default workspace cursor must blink"
        tmux(
            "send-keys",
            "-t",
            "main",
            "printf '\\033[?25l'; sleep 1; printf '\\033[?25h'",
            "Enter",
        )
        wait(fd, b"\x1b[?25l")
        wait(fd, b"\x1b[?25h")
        os.write(fd, b"\x02a")
        wait(fd, b"ai")
        os.write(fd, b"draft-kept")
        wait(fd, b"draft-kept")
        os.write(fd, b"\x02?")
        wait(fd, b"native Bash editing")
        os.write(fd, b"\x1b")
        pump(fd, 0.2)
        os.write(fd, b"\x1b")
        pump(fd, 0.3)
        os.write(fd, b"\x02a")
        wait(fd, b"ai")
        os.write(fd, b"convert\r")
        wait(fd, b"magick")
        pump(fd, 0.5)
        os.write(fd, b"\t")
        pump(fd, 0.5)
        os.write(fd, b"\x15printf 'native-roundtrip:%s\\n' ready\r")
        wait(fd, b"native-roundtrip:ready")
        # A global Agent is a normal persistent PTY split, with one output owner.
        original_pane = tmux(
            "display-message", "-p", "-t", "main", "#{pane_id}"
        ).strip()
        os.write(fd, b"\x02g")
        wait(fd, b"opencode-interface")
        agent_pane = tmux("display-message", "-p", "-t", "main", "#{pane_id}").strip()
        assert agent_pane != original_pane
        tmux("kill-pane", "-t", agent_pane)
        pump(fd, 0.5)
        os.write(fd, b"export PY_KEEP=alive; printf 'python:%s\\n' ready\r")
        wait(fd, b"python:ready")
        os.write(fd, b"sleep 20\r")
        pump(fd, 0.2)
        os.write(fd, b"\x03")
        pump(fd, 0.2)
        os.write(fd, b"printf 'interrupt:%s\\n' survived\r")
        wait(fd, b"interrupt:survived")
        before = tmux(
            "display-message", "-p", "-t", "main", "#{pane_width} #{pane_height}"
        )
        os.write(fd, b"\x02?")
        wait(fd, b"Workspace")
        wait(fd, b"create window") if b"create window" not in all_bytes else None
        os.write(fd, b"\x1b")
        pump(fd)
        os.write(fd, b"\x02p")
        wait(fd, b"Cosmos / actions")
        pump(fd)
        assert (
            tmux("display-message", "-p", "-t", "main", "#{pane_width} #{pane_height}")
            == before
        )
        os.write(fd, b"Settings\r")
        wait(fd, b"Cosmos / settings")
        pump(fd)
        os.write(fd, b"\x1b")
        pump(fd)
        os.write(fd, b"\x1b")
        pump(fd)
        original_window = tmux(
            "display-message", "-p", "-t", "main", "#{window_id}"
        ).strip()
        # Exercise actual terminal key names for both split directions.
        os.write(fd, b"\x02\x1b[57441u\x1b[53;2;37u")
        until(
            fd,
            lambda: len(
                tmux("list-panes", "-t", "main", "-F", "#{pane_id}").splitlines()
            )
            == 2,
        )
        split_panes = tmux(
            "list-panes", "-t", "main", "-F", "#{pane_id}|#{pane_left}"
        ).splitlines()
        assert int(split_panes[1].split("|")[1]) > 0
        right = split_panes[1].split("|")[0]
        os.write(fd, b"printf 'horizontal:%s\\n' ready\r")
        wait(fd, b"horizontal:ready")
        os.write(fd, b"\x02\x1b[D")
        pump(fd)
        assert (
            tmux("display-message", "-p", "-t", "main", "#{pane_id}").strip() != right
        )
        width_before = int(tmux("display-message", "-p", "-t", right, "#{pane_width}"))
        os.write(fd, b"\x02L")
        pump(fd)
        assert (
            int(tmux("display-message", "-p", "-t", right, "#{pane_width}"))
            < width_before
        )
        # Mouse coordinates are cells in this PTY (no pixel-size negotiation).
        x = int(tmux("display-message", "-p", "-t", right, "#{pane_left}")) + 2
        os.write(fd, f"\x1b[<0;{x};2M\x1b[<0;{x};2m".encode())
        until(
            fd,
            lambda: tmux("display-message", "-p", "-t", "main", "#{pane_id}").strip()
            == right,
        )
        tmux("kill-pane", "-t", right)
        pump(fd)
        os.write(fd, b"\x02\x1b[57447u\x1b[39;2;34u")
        until(
            fd,
            lambda: len(
                tmux("list-panes", "-t", "main", "-F", "#{pane_id}").splitlines()
            )
            == 2,
        )
        split_panes = tmux(
            "list-panes", "-t", "main", "-F", "#{pane_id}|#{pane_top}"
        ).splitlines()
        assert int(split_panes[1].split("|")[1]) > 0
        bottom = split_panes[1].split("|")[0]
        os.write(fd, b"\x02\x1b[A")
        pump(fd)
        tmux("kill-pane", "-t", bottom)
        pump(fd)
        os.write(fd, b"\x025")
        pump(fd)
        assert p.poll() is None, "missing window must not crash the frontend"
        target = tmux(
            "new-window",
            "-d",
            "-P",
            "-F",
            "#{window_id}",
            "-t",
            "main",
            "-n",
            "switch-target",
        ).strip()
        tmux("send-keys", "-t", target, "printf 'preview-target:%s\\n' ready", "Enter")
        tmux("new-session", "-d", "-s", "alternate")
        os.write(fd, b"\x02s")
        wait(fd, b"Switch")
        pump(fd)
        os.write(fd, b"switch-target")
        wait(fd, b"preview-target:ready")
        pump(fd)
        assert (
            tmux("display-message", "-p", "-t", "main", "#{window_id}").strip()
            == original_window
        ), "preview must not switch focus"
        assert (
            tmux(
                "display-message",
                "-p",
                "-t",
                original_window,
                "#{pane_width} #{pane_height}",
            )
            == before
        )
        os.write(fd, b"\x1b")
        pump(fd)
        assert (
            tmux("display-message", "-p", "-t", "main", "#{window_id}").strip()
            == original_window
        )
        os.write(fd, b"\x02s")
        wait(fd, b"Switch")
        os.write(fd, b"switch-target\r")
        until(
            fd,
            lambda: tmux("display-message", "-p", "-t", "main", "#{window_id}").strip()
            == target,
        )
        os.write(fd, b"\x02s")
        wait(fd, b"Switch")
        os.write(fd, b"alternate\r")
        until(
            fd,
            lambda: "alternate"
            in tmux("list-clients", "-F", "#{client_session}").splitlines(),
        )
        os.write(fd, b"\x02s")
        wait(fd, b"Switch")
        os.write(fd, b"main 0\r")
        until(
            fd,
            lambda: "main"
            in tmux("list-clients", "-F", "#{client_session}").splitlines(),
        )
        until(
            fd,
            lambda: tmux("display-message", "-p", "-t", "main", "#{window_id}").strip()
            == original_window,
        )
        os.write(fd, b"printf 'switch-state:%s\\n' \"$PY_KEEP\"\r")
        wait(fd, b"switch-state:alive")
        subprocess.run(
            [str(BIN), "mod", "add", str(ROOT / "examples/surface.mod.toml")],
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                str(BIN),
                "rpc",
                "mods.start",
                json.dumps({"id": "surface", "client": f"textual-{p.pid}"}),
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        wait(fd, b"Received keys: 0")
        os.write(fd, b"k")
        wait(fd, b"Received keys: 1")
        os.write(fd, b"\x1b")
        pump(fd)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 100, 800, 448))
        pump(fd)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 640, 384))
        pump(fd)
        os.write(fd, f"'{BIN}' open '{tmp}/image.png'\r".encode())
        wait(fd, b"\x1b_Ga=T,f=100")
        pump(fd)
        packets = re.findall(rb"\x1b_G([^;]*);([^\x1b]*)\x1b\\", bytes(all_bytes))
        chunks = []
        encoded = None
        for header, data in packets:
            if b"a=T" in header:
                chunks = []
            if data:
                chunks.append(data)
            if b"m=0" in header and chunks:
                encoded = base64.b64decode(b"".join(chunks))
        assert encoded and encoded.startswith(b"\x89PNG"), (
            "Kitty pixels must come from the unified Textual batch"
        )
        os.write(fd, b"\x02?")
        wait(fd, b"Viewer")
        pump(fd)
        assert b"a=d,d=I" in all_bytes
        os.write(fd, b"\x1b")
        wait(fd, b"\x1b_Ga=T,f=100")
        pump(fd)
        os.write(fd, b"+")
        wait(fd, b"\x1b_Ga=T,f=100")
        pump(fd)
        os.write(fd, b"\x02d")
        pump(fd)
        assert p.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        start = len(all_bytes)
        p, fd, slave, original = launch()
        if b"a=T" not in all_bytes[start:]:
            wait(fd, b"\x1b_Ga=T,f=100")
        os.write(fd, b"q")
        pump(fd)
        os.write(fd, b"printf 'reconnect:%s\\n' \"$PY_KEEP\"\r")
        wait(fd, b"reconnect:alive")
        os.write(fd, f"'{BIN}' open '{tmp}/document.pdf'\r".encode())
        wait(fd, b"1/3")
        pump(fd)
        os.write(fd, b"]")
        wait(fd, b"2/3")
        pump(fd)
        os.write(fd, b"q")
        pump(fd)
        os.write(fd, b"\x02d")
        pump(fd)
        assert p.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        print(
            json.dumps(
                dict(
                    hardware_cursor_blink=True,
                    application_cursor_visibility=True,
                    terminal_agent_cosmos_ui=True,
                    opencode_split=True,
                    horizontal_split=True,
                    pane_keyboard_focus=True,
                    pane_mouse_focus=True,
                    pane_resize=True,
                    vertical_split=True,
                    switcher_preview=True,
                    switcher_cancel=True,
                    cross_session_switch=True,
                    textual_grid=True,
                    shell_ctrl_c=True,
                    unified_kitty_batch=True,
                    context_help=True,
                    palette_settings=True,
                    no_pty_resize_for_overlay=True,
                    image_zoom=True,
                    pdf_pages=True,
                    reconnect=True,
                    terminal_restore=True,
                    mod_surface=True,
                    resize=True,
                )
            )
        )
    except Exception:
        print("clients", [(p.pid, p.poll()) for p in clients])
        print("terminal tail", bytes(all_bytes[-5000:]))
        raise
    finally:
        for p in clients:
            if p.poll() is None:
                p.terminate()
        for p in clients:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        subprocess.run(
            ["tmux", "-L", env["COSMOS_TMUX_SOCKET"], "kill-server"],
            env=env,
            capture_output=True,
        )
        subprocess.run([str(BIN), "stop"], env=env, capture_output=True)
        for fd in handles:
            os.close(fd)
