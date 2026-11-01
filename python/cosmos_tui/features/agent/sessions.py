"""Stable Cosmos/Tmux session management and private retained-history exports."""

from datetime import datetime, timezone
from pathlib import Path
import re

from cosmos_tui.features.agent.terminal import TerminalTools
from cosmos_tui.features.agent.profile import profile_root, write_private_json


class WorkspaceTools(TerminalTools):
    async def list_sessions(self):
        rows = await self.panes()
        sessions = {}
        for row in rows:
            entry = sessions.setdefault(
                row["session_id"],
                dict(id=row["session_id"], name=row["session_name"], panes=[]),
            )
            entry["panes"].append(
                dict(
                    pane=row["pane_id"],
                    window=row["window_id"],
                    program=row["pane_current_command"],
                )
            )
        return list(sessions.values())

    async def create_session(self, name, source_pane, workspace_token=None):
        self.check_workspace(workspace_token)
        self.backend.validate_name(name)
        source = await self.pane(source_pane)
        ident = await self.backend.cli(
            "new-session",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
            "-s",
            name,
            "-c",
            source["pane_current_path"],
            self.backend.shell_command(),
        )
        return await self.created_terminal(ident.strip())

    async def rename_target(self, target, name, workspace_token=None):
        self.check_workspace(workspace_token)
        if not isinstance(target, str) or not re.fullmatch(r"[$@%]\d+", target):
            raise ValueError("target must be a stable $session, @window or %pane ID")
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or any(not c.isprintable() for c in name)
        ):
            raise ValueError("name must be printable, 1–80 characters")
        field = {"$": "session_id", "@": "window_id", "%": "pane_id"}[target[0]]
        if not any(row[field] == target for row in await self.panes()):
            raise ValueError("target no longer exists")
        if target.startswith("$"):
            self.backend.validate_name(name)
            await self.backend.cli("rename-session", "-t", target, name)
        elif target.startswith("@"):
            await self.backend.cli("rename-window", "-t", target, name)
        else:
            await self.backend.cli(
                "set-option", "-p", "-t", target, "@cosmos_name", name
            )
        return dict(target=target, name=name)

    async def focus_pane(self, pane, client=None, workspace_token=None):
        self.check_workspace(workspace_token)
        await self.pane(pane)
        from cosmos_tui.features.agent.actions import ActionTools

        return await ActionTools(self.backend.argv[2]).ui_call(
            client, dict(operation="focus", pane=pane)
        )

    async def export_history(self, session, output=None):
        if not isinstance(session, str) or not re.fullmatch(r"\$\d+", session):
            raise ValueError("session must be a stable $ID")
        panes = [row for row in await self.panes() if row["session_id"] == session]
        if not panes:
            raise ValueError("session no longer exists")
        history = []
        for pane in panes:
            await self.pane(pane["pane_id"])
            text = await self.backend.cli(
                "capture-pane", "-p", "-t", pane["pane_id"], "-S", "-", "-E", "-"
            )
            await self.pane(pane["pane_id"])
            text = self.redact(text)
            raw = text.encode()
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError(
                    "pane history exceeds 16 MiB; export it explicitly with cosmos history"
                )
            history.append(dict(pane, text=text))
        path = (
            Path(output).expanduser()
            if output
            else profile_root()
            / "exports"
            / (
                "terminal-"
                + session[1:]
                + "-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                + ".json"
            )
        )
        write_private_json(
            path, dict(kind="cosmos-terminal-history", session=session, panes=history)
        )
        return dict(
            path=str(path.resolve()), panes=len(history), bytes=path.stat().st_size
        )
