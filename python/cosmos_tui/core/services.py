"""Zone-specific host APIs; shared rendering does not imply shared semantics."""

import shlex
from dataclasses import dataclass

from cosmos_tui.core import rpc
from cosmos_tui.ui.menus import CompactMenu


class SessionWindows:
    """Persistent window operations, delegating PTY/layout ownership to Tmux."""

    def __init__(self, backend):
        self.backend = backend

    async def open(self, argv=(), *, name=None, cwd=None):
        command = 'new-window -P -F "#{window_id}"'
        if name:
            command += " -n " + self.backend.quote(name)
        if cwd:
            command += " -c " + self.backend.quote(cwd)
        if argv:
            command += " " + self.backend.quote(shlex.join(argv))
        return (await self.backend.request(command))[0]

    async def split(self, pane, argv=(), *, horizontal=True):
        if not pane.startswith("%") or not pane[1:].isdigit():
            raise ValueError("expected a stable pane id")
        command = (
            "split-window -t "
            + pane
            + (" -h" if horizontal else " -v")
            + ' -c "#{pane_current_path}"'
        )
        if argv:
            command += " " + self.backend.quote(shlex.join(argv))
        return await self.backend.request(command)

    async def focus(self, window):
        # IDs come from backend inventory, never a display label.
        if not window.startswith("@") or not window[1:].isdigit():
            raise ValueError("expected a stable window id")
        await self.backend.request("select-window -t " + window)


class PopWindows:
    def __init__(self, app):
        self.app = app

    def actions(self, title, choices, callback):
        return self.app.push_screen(CompactMenu(title, choices), callback)


class NotificationEvents:
    """Actions emit notifications.action; publishers decide what a choice means."""

    def __init__(self, app=None):
        self.app = app

    async def publish(
        self,
        text,
        *,
        source="core",
        actions=(),
        level="info",
        ttl_ms=None,
        persistent=False,
        session_id=None,
    ):
        return await rpc.call(
            "notifications.publish",
            dict(
                text=text,
                source=source,
                actions=list(actions),
                level=level,
                ttl_ms=ttl_ms,
                persistent=persistent,
                session_id=session_id
                if session_id is not None
                else getattr(getattr(self.app, "backend", None), "session_id", None),
            ),
        )


@dataclass(frozen=True)
class FilePanelModel:
    """A file provider supplies these; this API performs no filesystem operations."""

    cwd: str
    entries: tuple[str, ...]
    selected: int | None = None
    preview: tuple[str, ...] = ()

    def content(self):
        if self.selected is not None and not 0 <= self.selected < len(self.entries):
            raise ValueError("selected file outside directory model")
        return {
            "title": self.cwd,
            "lines": [
                {
                    "text": ("› " if i == self.selected else "  ") + name,
                    "role": "acc" if i == self.selected else "fg",
                }
                for i, name in enumerate(self.entries)
            ]
            + (
                [{"text": line, "role": "mute"} for line in self.preview]
                if self.selected is not None
                else []
            ),
        }


@dataclass(frozen=True)
class PowerlineValue:
    owner: str
    source_pane: str
    text: str
    rows: int = 1


class PowerlineSlot:
    """Exclusive compact input/status slot; callers explicitly release ownership."""

    def __init__(self):
        self.active = None

    def publish(self, value):
        if not 1 <= value.rows <= 2:
            raise ValueError("powerline is limited to one or two rows")
        if self.active and self.active.owner != value.owner:
            raise RuntimeError("powerline is owned by " + self.active.owner)
        self.active = value

    def release(self, owner):
        if self.active and self.active.owner == owner:
            self.active = None
