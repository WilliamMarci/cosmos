"""Persistent tmux control adapter. Tmux, rather than Python, parses application VT."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from dataclasses import dataclass

from cosmos_tui.core.paths import PROJECT_ROOT


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
    copy_mode: bool = False
    selection: tuple | None = None
    selection_inclusive: bool = False
    selection_rectangle: bool = False
    copy_match: str = ""


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
                str(PROJECT_ROOT / "shell/cosmos.bash"),
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
            + " -F '#{pane_id}|#{pane_left}|#{pane_top}|#{pane_width}|#{pane_height}|#{pane_active}|#{window_zoomed_flag}|#{cursor_x}|#{cursor_y}|#{cursor_flag}|#{cursor_shape}|#{cursor_blinking}|#{@cosmos_viewer}|#{pane_in_mode}'"
        )
        panes = []
        zoomed = False
        for row in rows:
            fields = row.split("|", 13)
            if len(fields) != 14:
                continue
            (
                pane,
                x,
                y,
                w,
                h,
                active,
                zoom,
                cx,
                cy,
                visible,
                shape,
                blink,
                wire,
                mode,
            ) = fields
            copy_mode = mode not in ("", "0")
            if not re.fullmatch(r"%\d+", pane):
                raise RuntimeError("invalid pane ID")
            selection = None
            offset = 0
            inclusive = rectangle = False
            copy_match = ""
            if copy_mode:
                position = await self.request(
                    f"display-message -p -t {pane} '#{{copy_cursor_x}}|#{{copy_cursor_y}}|#{{scroll_position}}|#{{history_size}}|#{{selection_present}}|#{{selection_start_x}}|#{{selection_start_y}}|#{{selection_end_x}}|#{{selection_end_y}}|#{{mode-keys}}|#{{rectangle_toggle}}|#{{=256:search_match}}'"
                )
                if position:
                    values = position[0].split("|", 11)
                    cx, cy = values[:2]
                    offset, history_size = map(int, values[2:4])
                    inclusive, rectangle = values[9] == "vi", values[10] == "1"
                    copy_match = values[11]
                    if values[4] == "1":
                        sx, sy, ex, ey = map(int, values[5:9])
                        top = history_size - offset
                        selection = (sx, sy - top, ex, ey - top)
            width, height = int(w), int(h)
            if width * height > 262144:
                raise RuntimeError("pane exceeds cell budget")
            lines = await self.request(
                "capture-pane -p -e -C -N "
                + (f"-M -S {-offset} -E {height - 1 - offset} " if copy_mode else "")
                + f"-t {pane}"
            )
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
                    copy_mode or visible != "0",
                    shape or "default",
                    blink != "0",
                    copy_mode,
                    selection,
                    inclusive,
                    rectangle,
                    copy_match,
                )
            )
            zoomed = zoom == "1"
        if window is None:
            self.zoomed = zoomed
        return [p for p in panes if not zoomed or p.active]

    async def send(self, key, character=None):
        # Legacy terminals send NUL; Kitty reports an explicit Ctrl+Space.
        # Handle both before printable associated text can become a plain space.
        if key in ("ctrl+space", "ctrl+@", "ctrl+at", "ctrl-at", "ctrl+\x00"):
            await self.request("send-keys -- C-Space")
            return
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
