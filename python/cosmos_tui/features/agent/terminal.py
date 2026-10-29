"""Bounded Tmux tools for the Cosmos Agent; no UI or model dependencies."""

import asyncio
import re
import uuid
from types import SimpleNamespace

from cosmos_tui.input.mouse_protocol import encode
from cosmos_tui.terminal.tmux import Tmux

FIELDS = (
    "session_id",
    "session_name",
    "window_id",
    "window_index",
    "window_name",
    "pane_id",
    "pane_index",
    "pane_width",
    "pane_height",
    "cursor_x",
    "cursor_y",
    "pane_current_path",
    "pane_current_command",
    "alternate_on",
    "pane_in_mode",
    "mouse_any_flag",
    "mouse_button_flag",
    "mouse_all_flag",
    "mouse_utf8_flag",
    "mouse_sgr_flag",
)
NUMBERS = {
    "window_index",
    "pane_index",
    "pane_width",
    "pane_height",
    "cursor_x",
    "cursor_y",
}
FLAGS = {
    "alternate_on",
    "pane_in_mode",
    "mouse_any_flag",
    "mouse_button_flag",
    "mouse_all_flag",
    "mouse_utf8_flag",
    "mouse_sgr_flag",
}


class TerminalTools:
    def __init__(self, socket):
        self.backend = Tmux()
        # Use the service captured by the launcher, not a shell's inherited TMUX.
        self.backend.argv = self.backend.argv[:1] + ["-L", socket]

    async def panes(self):
        template = "\t".join("#{" + key + "}" for key in FIELDS)
        text = await self.backend.cli("list-panes", "-a", "-F", template)
        result = []
        for line in text.splitlines():
            values = line.split("\t")
            if len(values) != len(FIELDS):
                continue
            row = dict(zip(FIELDS, values))
            for key in NUMBERS:
                row[key] = int(row[key])
            for key in FLAGS:
                row[key] = row[key] == "1"
            result.append(row)
        return result

    async def pane(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"%\d+", ident):
            raise ValueError("pane must be a stable %ID returned by list_panes")
        for row in await self.panes():
            if row["pane_id"] == ident:
                return row
        raise ValueError(f"pane no longer exists in this Cosmos service: {ident}")

    async def read_screen(self, pane, history=0, wait_ms=0):
        if type(history) is not int or not 0 <= history <= 2000:
            raise ValueError("history must be between 0 and 2000 lines")
        if type(wait_ms) is not int or not 0 <= wait_ms <= 2000:
            raise ValueError("wait_ms must be between 0 and 2000")
        await asyncio.sleep(wait_ms / 1000)
        row = await self.pane(pane)
        args = ["capture-pane", "-p", "-t", pane]
        if history:
            args += ["-S", str(-history)]
        text = await self.backend.cli(*args)
        raw = text.encode("utf-8")
        row.update(
            text=raw[:65536].decode("utf-8", errors="ignore"),
            truncated=len(raw) > 65536,
        )
        return row

    async def send_text(self, pane, text):
        await self.pane(pane)
        if not isinstance(text, str) or len(text.encode()) > 32768:
            raise ValueError("text must be at most 32 KiB")
        if any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("control characters are not text; use send_keys")
        name = "cosmos-agent-" + uuid.uuid4().hex
        try:
            await self.backend.cli("set-buffer", "-b", name, "--", text)
            await self.backend.cli("paste-buffer", "-p", "-d", "-b", name, "-t", pane)
        finally:
            try:
                await self.backend.cli("delete-buffer", "-b", name)
            except RuntimeError:
                pass
        return {"pane": pane, "pasted": len(text), "return_sent": False}

    async def send_keys(self, pane, keys):
        await self.pane(pane)
        if not isinstance(keys, list) or not 1 <= len(keys) <= 64:
            raise ValueError("keys must contain 1–64 Tmux key names")
        allowed = r"(?:(?:C-|M-|S-)*(?:[!-~]|Left|Right|Up|Down|Home|End|PageUp|PageDown|Enter|Escape|Tab|BSpace|Delete|Space|F(?:[1-9]|1[0-2])))"
        if any(not isinstance(k, str) or not re.fullmatch(allowed, k) for k in keys):
            raise ValueError(
                "use named Tmux keys (Enter, C-c, Escape, Down…); send text with send_text"
            )
        await self.backend.cli("send-keys", "-t", pane, "--", *keys)
        return {"pane": pane, "keys": keys}

    async def mouse(self, pane, x, y, button="left", action="click"):
        row = await self.pane(pane)
        if (
            type(x) is not int
            or type(y) is not int
            or not (1 <= x <= row["pane_width"] and 1 <= y <= row["pane_height"])
        ):
            raise ValueError("mouse coordinates are one-based cells within the pane")
        buttons = {"left": 0, "middle": 1, "right": 2, "wheel_up": 64, "wheel_down": 65}
        if button not in buttons or action not in ("click", "press", "release", "move"):
            raise ValueError("unsupported mouse button or action")
        if not any(
            row[k] for k in ("mouse_any_flag", "mouse_button_flag", "mouse_all_flag")
        ):
            raise ValueError(
                "application has not enabled mouse tracking; use keyboard navigation"
            )
        flags = SimpleNamespace(
            **{
                key.removesuffix("_flag"): row[key]
                for key in FLAGS
                if key.startswith("mouse_")
            }
        )
        sequence = encode(
            flags,
            buttons[button],
            x,
            y,
            release=action == "release",
            motion=action == "move",
        )
        if sequence is None:
            raise ValueError("application has not enabled mouse motion")
        if action == "click" and button in ("left", "middle", "right"):
            sequence += encode(flags, buttons[button], x, y, release=True)
        await self.backend.cli(
            "send-keys", "-H", "-t", pane, *(f"{b:02x}" for b in sequence)
        )
        return {"pane": pane, "x": x, "y": y, "button": button, "action": action}

    async def create_terminal(self, source_pane):
        row = await self.pane(source_pane)
        ident = await self.backend.cli(
            "new-window",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            row["session_id"] + ":",
            "-c",
            row["pane_current_path"],
            "-n",
            "agent-terminal",
            self.backend.shell_command(),
        )
        return await self.read_screen(ident.strip(), wait_ms=100)
