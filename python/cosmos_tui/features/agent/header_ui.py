"""Taking-over chrome composed into the existing terminal surface."""

import asyncio
import time

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.geometry import Region
from textual.strip import Strip

from cosmos_tui.features.agent.control import ControlStore
from cosmos_tui.features.agent.headers import synchronize

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def header_text(record, width, palette, frame):
    active = record["state"] == "active"
    base = Style(color=palette["fg"], bgcolor=palette["base"])
    text = Text(
        " COSMOS ", style=Style(color="#b48ead", bgcolor=palette["base"], bold=True)
    )
    text.append("Taking over" if active else "PAUSED", style=base)
    if active:
        text.append(
            " │ " + SPINNER[frame % len(SPINNER)] + " ",
            style=Style(color=palette["accl"], bgcolor=palette["base"]),
        )
        text.append(record["task"], style=base)
    elif record["state"] == "ready":
        text.append(" · Ready for fresh observation", style=base)
    text.truncate(max(0, width), overflow="ellipsis")
    text.append(" " * max(0, width - text.cell_len), style=base)
    return text


def paint_headers(app, strip, y, width):
    for pane in app.panes:
        record = getattr(app, "_agent_headers", {}).get(pane.id)
        if not record or pane.y <= 0 or y != pane.y - 1:
            continue
        text = header_text(
            record,
            pane.width,
            app.role_colors,
            0
            if getattr(app, "settings", {}).get("reduced_motion", False)
            else int(time.monotonic() * 8),
        )
        rendered = Strip(
            Segment(s.text, s.style) for s in text.render(app.console, end="")
        )
        strip = Strip.join(
            [strip.crop(0, pane.x), rendered, strip.crop(pane.x + pane.width, width)]
        )
    return strip.crop(0, width)


class HeaderController:
    def __init__(self, app):
        self.app = app
        self.store = ControlStore(app.backend.argv[2])
        self.signature = None
        self.last_sync = 0
        self.records = []
        self.last_frame = None

    async def layout(self):
        if not self.store.path.exists():
            return
        signature = self.store.path.stat().st_mtime_ns
        now = time.monotonic()
        if signature != self.signature or now - self.last_sync > 2:
            self.records = await asyncio.to_thread(synchronize, self.app.backend.argv)
            self.signature = self.store.path.stat().st_mtime_ns
            self.last_sync = now

    def refresh(self, panes, terminal):
        previous = getattr(self.app, "_agent_headers", {})
        current = {row["pane"]: row for row in self.records}
        self.app._agent_headers = current
        frame = (
            0
            if self.app.settings.get("reduced_motion", False)
            else int(time.monotonic() * 8)
        )
        for pane in panes:
            before, after = previous.get(pane.id), current.get(pane.id)
            if (
                before != after
                or after
                and after["state"] == "active"
                and frame != self.last_frame
            ):
                if pane.y > 0:
                    terminal.refresh(Region(pane.x, pane.y - 1, pane.width, 1))
        self.last_frame = frame
