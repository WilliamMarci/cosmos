"""Persistent tmux control adapter. Tmux, rather than Python, parses application VT."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from dataclasses import dataclass

from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.terminal.child_graphics import KittyStream, unescape_output


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
    mouse_any: bool = False
    mouse_standard: bool = False
    mouse_button: bool = False
    mouse_all: bool = False
    mouse_utf8: bool = False
    mouse_sgr: bool = False
    index: int = 0
    window_id: str = ""
    session_id: str = ""
    name: str = ""
    history_size: int = 0
    scroll_position: int = 0


class Tmux:
    def __init__(self, session="main"):
        self.validate_target(session)
        self.session = session
        self.session_id = None
        self.created = False
        self.argv = [
            os.getenv("COSMOS_TMUX", "tmux"),
            "-L",
            os.getenv("COSMOS_TMUX_SOCKET", "cosmos"),
        ]
        self.lock = asyncio.Lock()
        self.process = None
        self.reader_task = None
        self.reader_error = None
        self.response_token = None
        self.response_lines = []
        self.response_size = 0
        self.response_future = None
        self.child_streams = {}
        self.child_graphics = []
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
    def validate_name(session):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
            raise ValueError("invalid session name")

    @staticmethod
    def validate_target(value):
        if not re.fullmatch(r"\$\d+", value):
            Tmux.validate_name(value)

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

    async def resolve_session_id(self, name=None):
        """Resolve an exact name to its stable `$N` ID.

        Tmux target-session parsing accepts an exact name, then a name prefix,
        then a glob. Cosmos session names are exact identities, so operations
        must never use an ambiguous name target.
        """
        name = self.session if name is None else name
        try:
            output = await self.cli(
                "list-sessions", "-F", "#{session_id}\t#{session_name}"
            )
        except RuntimeError as error:
            message = str(error)
            if "no server running" in message or "No such file or directory" in message:
                return None
            raise
        for row in output.splitlines():
            session_id, _, session_name = row.partition("\t")
            if session_name == name or session_id == name:
                return session_id
        return None

    async def connect(self):
        self.created = False
        self.reader_error = None
        self.session_id = await self.resolve_session_id()
        if self.session_id is None:
            if self.session.startswith("$"):
                raise ValueError(f"session not found: {self.session}")
            try:
                self.session_id = (
                    await self.cli(
                        "-f",
                        "/dev/null",
                        "new-session",
                        "-d",
                        "-P",
                        "-F",
                        "#{session_id}",
                        "-s",
                        self.session,
                        "-c",
                        str(Path.home()),
                        self.shell_command(),
                    )
                ).strip()
            except RuntimeError:
                # Another client may have created the exact session in between.
                self.session_id = await self.resolve_session_id()
                if self.session_id is None:
                    raise
            else:
                self.created = True
        if not re.fullmatch(r"\$\d+", self.session_id or ""):
            raise RuntimeError("invalid session ID")
        self.session = (
            await self.cli(
                "display-message", "-p", "-t", self.session_id, "#{session_name}"
            )
        ).strip()
        await self.cli(
            "set-option",
            "-t",
            self.session_id,
            "default-command",
            self.shell_command(),
        )
        # Refuse capturing our own physical client from its backend pane.
        if os.getenv("TMUX_PANE"):
            socket = (await self.cli("display-message", "-p", "#{socket_path}")).strip()
            current = os.getenv("TMUX", "").split(",")[0]
            if os.path.realpath(current) == os.path.realpath(socket):
                panes = (
                    await self.cli(
                        "list-panes",
                        "-s",
                        "-t",
                        self.session_id,
                        "-F",
                        "#{pane_id}",
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
            "-t",
            self.session_id,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            limit=16 * 1024 * 1024,
        )
        await self._response()
        self.reader_task = asyncio.create_task(self._read_loop())
        await self.install_bell_hook()
        return self.created

    async def install_bell_hook(self):
        # One stable hook slot per Cosmos tmux server, not one publisher/client.
        binary = os.getenv("COSMOS_BINARY", str(PROJECT_ROOT / "target/release/cosmos"))
        environment = ["env"]
        for name in ("HOME", "XDG_RUNTIME_DIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME"):
            environment += ["-u", name]
        environment += [
            f"{name}={os.environ[name]}"
            for name in ("HOME", "XDG_RUNTIME_DIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME")
            if name in os.environ
        ]
        payload = json.dumps(
            {
                "text": "Terminal bell · window #{hook_window}",
                "source": "terminal:#{hook_window}",
                "level": "info",
                "session_id": "#{hook_session}",
            }
        )
        command = (
            shlex.join(environment + [binary, "rpc", "notifications.publish", payload])
            + " >/dev/null 2>&1"
        )
        await self.cli(
            "set-hook", "-g", "alert-bell[900]", "run-shell -b " + shlex.quote(command)
        )
        await self.cli("set-window-option", "-g", "monitor-bell", "on")
        await self.cli("set-option", "-g", "bell-action", "any")

    async def _response(self):
        token = None
        lines = []
        size = 0
        async with asyncio.timeout(3):
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise EOFError("terminal session ended")
                if token is None and line.startswith(b"%output "):
                    self._handle_output(line)
                    continue
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

    def _handle_output(self, line):
        try:
            _, pane, data = line.split(b" ", 2)
            pane_id = pane.decode("ascii")
        except (ValueError, UnicodeDecodeError):
            return
        stream = self.child_streams.get(pane_id)
        if stream is None:
            stream = self.child_streams[pane_id] = KittyStream()
        try:
            raw = unescape_output(data.rstrip(b"\r\n"))
            sequences = stream.feed(raw)
        except Exception:
            logging.getLogger(__name__).warning(
                "could not parse pane graphics output", exc_info=True
            )
            return
        for sequence in sequences:
            self.child_graphics.append((pane_id, sequence))

    def take_child_graphics(self):
        graphics, self.child_graphics = self.child_graphics, []
        return graphics

    def _set_response(self, result=None, error=None):
        future = self.response_future
        self.response_future = None
        self.response_token = None
        self.response_lines = []
        self.response_size = 0
        if future is None or future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result or [])

    async def _read_loop(self):
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise EOFError("terminal session ended")
                if self.response_token is None and line.startswith(b"%output "):
                    self._handle_output(line)
                    continue
                text = line.decode(errors="replace").rstrip("\r\n")
                if self.response_token is None:
                    if text.startswith("%begin "):
                        self.response_token = text[7:]
                        self.response_lines = []
                        self.response_size = 0
                    elif text.startswith("%exit"):
                        raise EOFError("terminal session ended")
                    continue
                if text == f"%end {self.response_token}":
                    self._set_response(result=self.response_lines)
                elif text == f"%error {self.response_token}":
                    self._set_response(
                        error=RuntimeError("\n".join(self.response_lines))
                    )
                else:
                    self.response_size += len(line)
                    if self.response_size > 8 * 1024 * 1024:
                        self._set_response(
                            error=RuntimeError("backend response exceeds budget")
                        )
                    else:
                        self.response_lines.append(text)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.reader_error = error
            self._set_response(error=error)
        finally:
            if self.response_future is not None and not self.response_future.done():
                self._set_response(error=EOFError("terminal session ended"))

    async def request(self, command):
        async with self.lock:
            if self.reader_error is not None:
                raise EOFError("terminal session ended") from self.reader_error
            if self.process is None or self.process.returncode is not None:
                raise EOFError("terminal session ended")
            future = asyncio.get_running_loop().create_future()
            self.response_future = future
            try:
                self.process.stdin.write((command + "\n").encode())
                await self.process.stdin.drain()
                async with asyncio.timeout(3):
                    return await future
            except TimeoutError as error:
                await self.close()
                raise EOFError(
                    "backend control connection ended; session is retained"
                ) from error
            except (BrokenPipeError, ConnectionError) as error:
                await self.close()
                raise EOFError(
                    "backend control connection ended; session is retained"
                ) from error
            finally:
                if self.response_future is future:
                    self.response_future = None

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
        self.session_id = window["session_id"]
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
            + " -F '#{pane_id}|#{pane_left}|#{pane_top}|#{pane_width}|#{pane_height}|#{pane_active}|#{window_zoomed_flag}|#{cursor_x}|#{cursor_y}|#{cursor_flag}|#{cursor_shape}|#{cursor_blinking}|#{@cosmos_viewer}|#{pane_in_mode}|#{mouse_any_flag}#{mouse_standard_flag}#{mouse_button_flag}#{mouse_all_flag}#{mouse_utf8_flag}#{mouse_sgr_flag}|#{pane_index}|#{window_id}|#{session_id}|#{@cosmos_name}'"
        )
        panes = []
        zoomed = False
        for row in rows:
            fields = row.split("|", 18)
            if len(fields) not in (15, 19):
                continue
            identities = fields[15:]
            fields = fields[:15]
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
                mouse_flags,
            ) = fields
            mouse = [digit == "1" for digit in f"{mouse_flags:0<6}"[:6]]
            copy_mode = mode not in ("", "0")
            if not re.fullmatch(r"%\d+", pane):
                raise RuntimeError("invalid pane ID")
            selection = None
            offset = 0
            history_size = 0
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
                    mouse_any=mouse[0],
                    mouse_standard=mouse[1],
                    mouse_button=mouse[2],
                    mouse_all=mouse[3],
                    mouse_utf8=mouse[4],
                    mouse_sgr=mouse[5],
                    index=int(identities[0]) if identities else len(panes),
                    window_id=identities[1] if identities else (window or ""),
                    session_id=identities[2] if identities else (self.session_id or ""),
                    name=identities[3] if identities else "",
                    history_size=history_size,
                    scroll_position=offset,
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

    async def send_bytes(self, target, data):
        """Write raw bytes to a pane PTY without Tmux key-name translation."""
        if not re.fullmatch(r"%\d+", target):
            raise ValueError("invalid pane ID")
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("mouse report must be non-empty bytes")
        payload = " ".join(f"{byte:02x}" for byte in data)
        await self.request(f"send-keys -H -t {target} {payload}")

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
        task = self.reader_task
        self.reader_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()


def in_cosmos_pane():
    """Detect the actual backend socket without starting a server."""
    actual = os.getenv("TMUX", "").split(",")[0]
    if not actual or not re.fullmatch(r"%[0-9]+", os.getenv("TMUX_PANE", "")):
        return False
    try:
        result = subprocess.run([os.getenv("COSMOS_TMUX", "tmux"), "-L", os.getenv("COSMOS_TMUX_SOCKET", "cosmos"), "display-message", "-p", "#{socket_path}"], capture_output=True, text=True, timeout=3)
        return result.returncode == 0 and bool(result.stdout.strip()) and os.path.realpath(actual) == os.path.realpath(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False
