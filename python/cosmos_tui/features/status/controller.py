"""Cache active-pane directory/program and Git metadata; compose status data."""

import asyncio
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import time

from cosmos_tui.core.controller import Controller
from cosmos_tui.features.status.bar import StatusBar


class StatusController(Controller):
    def __init__(self, app):
        super().__init__(app)
        self.cached = None
        self.updated = 0
        self.metadata = ("", "")
        self.branch = ""

    async def refresh(self):
        app = self.app
        pane = app.active()
        key = pane.id if pane else None
        now = time.monotonic()
        if pane and (key != self.cached or now - self.updated >= 2):
            self.cached, self.updated = key, now
            rows = await app.backend.request(
                f"display-message -p -t {pane.id} "
                + shlex.quote(
                    "#{pane_current_path}\t#{?@cosmos_agent,cosmos-agent,#{pane_current_command}}"
                )
            )
            parts = "\n".join(rows).split("\t", 1)
            self.metadata = tuple(parts) if len(parts) == 2 else ("", "")
            self.branch = ""
            path = self.metadata[0]
            if path:
                try:
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
                    }
                    process = await asyncio.create_subprocess_exec(
                        "git",
                        "-C",
                        path,
                        "symbolic-ref",
                        "--short",
                        "HEAD",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        env=env,
                    )
                    try:
                        output, _ = await asyncio.wait_for(process.communicate(), 1)
                        if process.returncode == 0:
                            self.branch = output.decode(errors="replace").strip()
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                except OSError:
                    pass
        path, program = self.metadata
        mode, label, details = "cosmos", "COSMOS", ""
        file_info = None
        identity = None
        history = ""
        if pane:
            if pane.copy_mode:
                total = pane.history_size + pane.height
                row = max(
                    1,
                    min(
                        total,
                        pane.history_size - pane.scroll_position + pane.cursor[1] + 1,
                    ),
                )
                history = f"COPY {row}/{total}:{pane.cursor[0] + 1} {round(row / max(1, total) * 100)}%"
        if pane and pane.viewer:
            state = json.loads(base64.b64decode(pane.viewer))
            suffix = Path(state["path"]).suffix.lower()
            mode, label = (
                ("doc", "DOC")
                if suffix in (".pdf", ".epub", ".md", ".markdown", ".html", ".htm")
                else ("image", "IMAGE")
            )
            if state.get("kind") == "files":
                mode, label = "files", "FILES"
                try:
                    file_info = await asyncio.to_thread(
                        app.reader_ui.files.status, state
                    )
                except (OSError, ValueError, RuntimeError):
                    file_info = dict(
                        name="Unavailable", size="", permissions="", position=""
                    )
            path = "" if file_info is not None else state["path"]
        elif Path(program).name in ("cosmos-agent", "opencode", "claude", "codex"):
            mode, label = "agent", "AGENT"
        elif Path(program).name == "yazi":
            mode, label = "files", "FILES"
        home = str(Path.home())
        if path == home or path.startswith(home + "/"):
            path = "~" + path[len(home) :]
        index, name = 0, app.backend.session
        for _, tab_index, active, tab_name in app.backend.tabs:
            if active == "1":
                index, name = tab_index, tab_name
                break
        if pane:
            window_index = next((tab[1] for tab in app.backend.tabs if tab[0] == pane.window_id), index)
            position = f"{window_index}:{pane.index}" if len(app.backend.tabs) > 1 else str(pane.index)
            identity = f"{app.backend.session}·{position}"
        center = [
            (row["text"], row.get("role", "mute"))
            for widget in getattr(app, "status_widgets", [])
            for row in widget.get("content", {}).get("lines", [])[:1]
        ]
        app.query_one("#status", StatusBar).present(
            label=label,
            index=index,
            name=name,
            path=path,
            branch=self.branch if not (pane and pane.viewer) else "",
            details=details,
            center=center,
            clock=datetime.now().astimezone().strftime("%H:%M %b %d"),
            mode=mode,
            file_info=file_info,
            identity=identity,
            history=history,
        )
