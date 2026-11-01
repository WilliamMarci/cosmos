"""Bounded Tmux tools for the Cosmos Agent; no UI or model dependencies."""

import asyncio
import re
import uuid
from types import SimpleNamespace

from cosmos_tui.input.mouse_protocol import encode
from cosmos_tui.terminal.tmux import Tmux
from cosmos_tui.features.agent.tasks.tools import TaskTools
from cosmos_tui.features.agent.history import HistoryTools
from cosmos_tui.features.agent.workspace_grants import WorkspaceGrants
from cosmos_tui.features.agent.control_tools import ControlledInput
from cosmos_tui.features.agent.context import ContextTools
from cosmos_tui.features.agent.monitor.tools import TerminalWatches

FIELDS = (
    "pid",
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
    "pane_dead",
    "@cosmos_private",
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
    "pane_dead",
    "alternate_on",
    "pane_in_mode",
    "mouse_any_flag",
    "mouse_button_flag",
    "mouse_all_flag",
    "mouse_utf8_flag",
    "mouse_sgr_flag",
}


class TerminalTools(
    ContextTools, ControlledInput, TerminalWatches, HistoryTools, WorkspaceGrants, TaskTools
):
    def __init__(self, socket):
        from cosmos_tui.features.agent.binding import WorkspaceBinding

        self.binding = WorkspaceBinding(socket)
        self.owner = uuid.uuid4().hex
        self.observation_requests = {}
        self.control_geometry = {}
        self.control_tokens = {}
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
            row["private"] = row.pop("@cosmos_private") in ("1", "on", "true")
            if row["private"]:
                row["pane_current_path"] = ""
                row["pane_current_command"] = ""
            row["display_id"] = row["session_id"][1:] + ":" + row["pane_id"][1:]
            result.append(row)
        self.binding.validate(result)
        return result

    async def workspace_info(self):
        rows = await self.panes()
        return dict(
            service_id=self.binding.validate(rows),
            scope="cosmos_workspace",
            capabilities=[
                "sessions",
                "terminals",
                "views",
                "actions",
                "retained_history",
                "tasks",
            ],
            host_commands="separate_native_permission",
            system_isolation=False,
        )

    async def pane(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"%\d+", ident):
            raise ValueError("pane must be a stable %ID returned by list_panes")
        for row in await self.panes():
            if row["pane_id"] == ident:
                if row["private"]:
                    raise PermissionError("Pane is private; Agent access is disabled")
                return row
        raise ValueError(f"pane no longer exists in this Cosmos service: {ident}")

    async def resolve_target(self, target):
        """Resolve stable IDs; display IDs use pane ID, never pane index."""
        if not isinstance(target, str) or not re.fullmatch(
            r"(?:%[0-9]+|[0-9]+:[0-9]+)", target
        ):
            raise ValueError("target must be %pane or session:pane, e.g. 1:4")
        for row in await self.panes():
            if target in (row["pane_id"], row["display_id"]):
                if row["private"]:
                    raise PermissionError("Pane is private; Agent access is disabled")
                return {
                    key: row[key]
                    for key in (
                        "pane_id",
                        "session_id",
                        "window_id",
                        "display_id",
                        "session_name",
                        "pane_current_path",
                        "pane_current_command",
                        "pane_width",
                        "pane_height",
                    )
                }
        raise ValueError("target no longer exists in this Cosmos service")

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
        await self.pane(pane)
        text = self.redact(text)
        raw = text.encode("utf-8")
        row.update(
            text=raw[:65536].decode("utf-8", errors="ignore"),
            truncated=len(raw) > 65536,
        )
        return row

    @staticmethod
    def redact(text):
        from cosmos_tui.features.agent.profile import load_profile
        from rich.cells import cell_len

        _, credentials = load_profile()
        for value in sorted(set(credentials.values()), key=len, reverse=True):
            if value:
                text = text.replace(value, "*" * cell_len(value))
        return text

    async def observe(self, pane, layers=None, region=None, since=None):
        from cosmos_tui.features.agent.observation.snapshot import (
            LAYERS,
            Observations,
            build,
        )

        layers = ["text", "controls"] if layers is None else layers
        if (
            not isinstance(layers, list)
            or not layers
            or any(layer not in LAYERS for layer in layers)
        ):
            raise ValueError(
                "layers must be a nonempty list of text, presentation, controls"
            )
        row = await self.pane(pane)
        raw = await self.backend.cli("capture-pane", "-p", "-e", "-t", pane)
        current = await self.pane(pane)
        if any(
            row[k] != current[k]
            for k in ("pane_width", "pane_height", "pane_current_command")
        ):
            raise ValueError("Pane changed during capture; observe again")
        if len(raw.encode()) > 65536:
            raise ValueError("Observation exceeds 64 KiB; use a smaller terminal")
        result = build(row, self.redact(raw), layers, region)
        if not hasattr(self, "observations"):
            self.observations = Observations()
        self.observation_requests[result["snapshot_id"]] = (pane, region)
        while len(self.observation_requests) > 32:
            del self.observation_requests[next(iter(self.observation_requests))]
        return self.observations.finish(result, since)

    async def _send_text(self, pane, text):
        await self.pane(pane)
        if not isinstance(text, str) or len(text.encode()) > 32768:
            raise ValueError("text must be at most 32 KiB")
        if any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("control characters are not text; use send_keys")
        name = "cosmos-agent-" + uuid.uuid4().hex
        try:
            await self.backend.cli("set-buffer", "-b", name, "--", text)
            from cosmos_tui.features.agent.control import ControlStore

            ControlStore(self.backend.argv[2]).check(pane)
            await self.backend.cli("paste-buffer", "-p", "-d", "-b", name, "-t", pane)
        finally:
            try:
                await self.backend.cli("delete-buffer", "-b", name)
            except RuntimeError:
                pass
        return {"pane": pane, "pasted": len(text), "return_sent": False}

    async def _send_keys(self, pane, keys):
        await self.pane(pane)
        if not isinstance(keys, list) or not 1 <= len(keys) <= 64:
            raise ValueError("keys must contain 1–64 Tmux key names")
        allowed = r"(?:(?:C-|M-|S-)*(?:[!-~]|Left|Right|Up|Down|Home|End|PageUp|PageDown|Enter|Escape|Tab|BSpace|Delete|Space|F(?:[1-9]|1[0-2])))"
        if any(not isinstance(k, str) or not re.fullmatch(allowed, k) for k in keys):
            raise ValueError(
                "use named Tmux keys (Enter, C-c, Escape, Down…); send text with send_text"
            )
        from cosmos_tui.features.agent.control import ControlStore

        ControlStore(self.backend.argv[2]).check(pane)
        await self.backend.cli("send-keys", "-t", pane, "--", *keys)
        return {"pane": pane, "keys": keys}

    async def _mouse(self, pane, x, y, button="left", action="click"):
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
        from cosmos_tui.features.agent.control import ControlStore

        ControlStore(self.backend.argv[2]).check(pane)
        await self.backend.cli(
            "send-keys", "-H", "-t", pane, *(f"{b:02x}" for b in sequence)
        )
        return {"pane": pane, "x": x, "y": y, "button": button, "action": action}

    async def create_terminal(self, source_pane, workspace_token=None):
        self.check_workspace(workspace_token)
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
        return await self.created_terminal(ident.strip())

    async def created_terminal(self, pane):
        """A creation acknowledgement with actual cwd and a reusable fresh snapshot."""
        from cosmos_tui.features.agent.compact import compact_snapshot

        await asyncio.sleep(0.1)
        observed = await self.observe(pane, ["text"])
        row = await self.pane(pane)
        return dict(
            pane_id=row["pane_id"],
            session_id=row["session_id"],
            window_id=row["window_id"],
            display_id=row["display_id"],
            pane_current_path=row["pane_current_path"],
            program=row["pane_current_command"],
            startup="exited" if row["pane_dead"] else "process_running",
            shell_ready=None,
            focus_changed=False,
            snapshot=compact_snapshot(observed),
        )
