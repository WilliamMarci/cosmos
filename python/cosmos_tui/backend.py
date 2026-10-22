"""Persistent tmux control adapter. Tmux, rather than Python, parses application VT."""

from __future__ import annotations
import asyncio
import os
import re
import shlex
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Pane:
    id: str
    x: int
    y: int
    width: int
    height: int
    active: bool
    lines: list[str]
    viewer: str
    cursor: tuple[int, int]
    cursor_visible: bool = True
    cursor_shape: str = "default"
    cursor_blinking: bool = True


class Tmux:
    def __init__(self, session="main"):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
            raise ValueError("invalid session name")
        self.session = session
        self.argv = [
            os.getenv("COSMOS_TMUX", "tmux"),
            "-L",
            os.getenv("COSMOS_TMUX_SOCKET", "cosmos"),
        ]
        self.lock = asyncio.Lock()
        self.process = None
        self.size = None
        self.tabs = []
        self.zoomed = False

    async def cli(self, *args):
        process = await asyncio.create_subprocess_exec(
            *self.argv,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(process.communicate(), 5)
        if process.returncode:
            raise RuntimeError(err.decode(errors="replace").strip())
        return out.decode(errors="replace")

    @staticmethod
    def shell_command():
        return shlex.join(
            [
                "bash",
                "--rcfile",
                str(Path(__file__).resolve().parents[2] / "shell/cosmos.bash"),
                "-i",
            ]
        )

    async def connect(self):
        try:
            await self.cli("has-session", "-t", self.session)
        except RuntimeError:
            await self.cli(
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-s",
                self.session,
                self.shell_command(),
            )
        await self.cli(
            "set-option", "-t", self.session, "default-command", self.shell_command()
        )
        # Refuse capturing our own physical client from its backend pane.
        if os.getenv("TMUX_PANE"):
            socket = (await self.cli("display-message", "-p", "#{socket_path}")).strip()
            current = os.getenv("TMUX", "").split(",")[0]
            if os.path.realpath(current) == os.path.realpath(socket):
                panes = (
                    await self.cli(
                        "list-panes", "-s", "-t", self.session, "-F", "#{pane_id}"
                    )
                ).splitlines()
                if os.environ["TMUX_PANE"] in panes:
                    raise RuntimeError(
                        "Detach first; a workspace cannot capture its own client"
                    )
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
        self.process = await asyncio.create_subprocess_exec(
            *self.argv,
            "-C",
            "attach-session",
            "-f",
            "no-output",
            "-t",
            self.session,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            limit=1024 * 1024,
        )
        await self._response()

    async def _response(self):
        token = None
        lines = []
        size = 0
        async with asyncio.timeout(3):
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise EOFError("terminal session ended")
                text = line.decode(errors="replace").rstrip("\r\n")
                if token is None:
                    if text.startswith("%begin "):
                        token = text[7:]
                    elif text.startswith("%exit"):
                        raise EOFError("terminal session ended")
                elif text == f"%end {token}":
                    return lines
                elif text == f"%error {token}":
                    raise RuntimeError("\n".join(lines))
                else:
                    size += len(line)
                    if size > 8 * 1024 * 1024:
                        raise RuntimeError("backend response exceeds budget")
                    lines.append(text)

    async def request(self, command):
        async with self.lock:
            try:
                self.process.stdin.write((command + "\n").encode())
                await self.process.stdin.drain()
                return await self._response()
            except (TimeoutError, ConnectionError) as error:
                await self.close()
                raise EOFError(
                    "backend control connection ended; session is retained"
                ) from error

    @staticmethod
    def quote(text):
        return (
            '"'
            + text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            + '"'
        )

    async def resize(self, width, height):
        # Control-mode dimensions already describe the window content area.
        size = (max(1, width), max(1, height))
        if self.size != size:
            await self.request(f"refresh-client -C {size[0]}x{size[1]}")
            self.size = size

    async def inventory(self):
        rows = await self.request(
            "list-windows -a -F '#{session_id}|#{window_id}|#{window_index}|#{window_active}|#{window_name}'"
        )
        sessions = {}
        windows = []
        for row in rows:
            sid, wid, index, active, name = row.split("|", 4)
            if not re.fullmatch(r"\$\d+", sid) or not re.fullmatch(r"@\d+", wid):
                raise RuntimeError(f"invalid session/window ID: {sid!r}, {wid!r}")
            if sid not in sessions:
                sessions[sid] = " ".join(
                    await self.request(
                        f"display-message -p -t {sid} '#{{session_name}}'"
                    )
                )
            windows.append(
                dict(
                    session_id=sid,
                    session=sessions[sid],
                    window_id=wid,
                    index=index,
                    name=name,
                    active=active == "1",
                )
            )
        return windows

    async def select_window(self, window):
        sid, wid = window["session_id"], window["window_id"]
        if not re.fullmatch(r"\$\d+", sid) or not re.fullmatch(r"@\d+", wid):
            raise RuntimeError(f"invalid session/window ID: {sid!r}, {wid!r}")
        await self.request(f"switch-client -t {sid}")
        await self.request(f"select-window -t {sid}:{wid}")
        self.session = window["session"]
        self.size = None

    async def snapshot(self, window=None):
        target = ""
        if window is not None:
            if not re.fullmatch(r"@\d+", window):
                raise RuntimeError("invalid window ID")
            target = f"-t {window}"
        else:
            self.tabs = [
                row.split("|", 3)
                for row in await self.request(
                    "list-windows -F '#{window_id}|#{window_index}|#{window_active}|#{window_name}'"
                )
            ]
        rows = await self.request(
            "list-panes "
            + target
            + " -F '#{pane_id}|#{pane_left}|#{pane_top}|#{pane_width}|#{pane_height}|#{pane_active}|#{window_zoomed_flag}|#{cursor_x}|#{cursor_y}|#{cursor_flag}|#{cursor_shape}|#{cursor_blinking}|#{@cosmos_viewer}'"
        )
        panes = []
        zoomed = False
        for row in rows:
            fields = row.split("|", 12)
            if len(fields) != 13:
                continue
            pane, x, y, w, h, active, zoom, cx, cy, visible, shape, blink, wire = fields
            if not re.fullmatch(r"%\d+", pane):
                raise RuntimeError("invalid pane ID")
            width, height = int(w), int(h)
            if width * height > 262144:
                raise RuntimeError("pane exceeds cell budget")
            lines = await self.request(f"capture-pane -p -e -C -N -t {pane}")
            lines = [
                re.sub(
                    r"\\([0-7]{3}|\\)",
                    lambda m: chr(int(m[1], 8)) if m[1] != "\\" else "\\",
                    line,
                )
                for line in lines
            ]
            panes.append(
                Pane(
                    pane,
                    int(x),
                    int(y),
                    width,
                    height,
                    active == "1",
                    lines,
                    wire,
                    (int(cx), int(cy)),
                    visible != "0",
                    shape or "default",
                    blink != "0",
                )
            )
            zoomed = zoom == "1"
        if window is None:
            self.zoomed = zoomed
        return [p for p in panes if not zoomed or p.active]

    async def send(self, key, character=None):
        names = {
            "enter": "Enter",
            "escape": "Escape",
            "backspace": "BSpace",
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
            "home": "Home",
            "end": "End",
            "pageup": "PPage",
            "pagedown": "NPage",
            "delete": "DC",
            "insert": "IC",
            "tab": "Tab",
            "shift+tab": "BTab",
        }
        if character and character.isprintable():
            await self.request("send-keys -l -- " + self.quote(character))
        else:
            name = names.get(key)
            if key.startswith("ctrl+") and len(key) == 6:
                name = "C-" + key[-1]
            if re.fullmatch(r"f\d{1,2}", key):
                name = key.upper()
            if name:
                await self.request("send-keys -- " + self.quote(name))

    async def paste(self, text, target=None):
        if target is not None and not re.fullmatch(r"%\d+", target):
            raise ValueError("invalid pane ID")
        process = await asyncio.create_subprocess_exec(
            *self.argv,
            "load-buffer",
            "-b",
            f"cosmos-py-{os.getpid()}",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await process.communicate(text[:8192].encode())
        if process.returncode:
            raise RuntimeError(err.decode(errors="replace"))
        await self.request(
            f"paste-buffer -d -p -b cosmos-py-{os.getpid()}"
            + (f" -t {target}" if target else "")
        )

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
