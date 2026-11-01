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
    else:
        text.append(" │ ⏸︎ ", style=base)
    if record["state"] == "ready":
        text.append(" · Ready for fresh observation", style=base)
    text.truncate(max(0, width), overflow="ellipsis")
    text.append(" " * max(0, width - text.cell_len), style=base)
    return text


def pointer_cell(record, pane):
    pointer = record.get("pointer") if record and record["state"] == "active" else None
    if not pointer or (pointer["width"], pointer["height"]) != (
        pane.width,
        pane.height,
    ):
        return None
    x, y = pointer["x"], pointer["y"]
    if not (1 <= x <= pane.width and 1 <= y <= pane.height):
        return None
    return pane.x + x - 1, pane.y + y - 1


def paint_headers(app, strip, y, width):
    reduced = getattr(app, "settings", {}).get("reduced_motion", False)
    for pane in app.panes:
        record = getattr(app, "_agent_headers", {}).get(pane.id)
        if not record:
            continue
        if pane.y > 0 and y == pane.y - 1:
            text = header_text(
                record,
                pane.width,
                app.role_colors,
                0 if reduced else int(time.monotonic() * 8),
            )
            rendered = Strip(
                Segment(s.text, s.style) for s in text.render(app.console, end="")
            )
            strip = Strip.join(
                [
                    strip.crop(0, pane.x),
                    rendered,
                    strip.crop(pane.x + pane.width, width),
                ]
            )
        point = pointer_cell(record, pane)
        if point and point[1] == y and (reduced or int(time.monotonic() * 3) % 2 == 0):
            x = point[0]
            marker = Strip(
                [
                    Segment(
                        "◆",
                        Style(
                            color="#63c5da", bgcolor=app.role_colors["base"], bold=True
                        ),
                    )
                ]
            )
            strip = Strip.join([strip.crop(0, x), marker, strip.crop(x + 1, width)])
    return strip.crop(0, width)


class HeaderController:
    def __init__(self, app):
        self.app = app
        self.store = ControlStore(app.backend.argv[2])
        self.signature = None
        self.last_sync = 0
        self.records = []
        self.last_frame = None
        self.timer = app.set_interval(1 / 8, self.animate)

    def animate(self):
        if self.app.settings.get("reduced_motion", False):
            return
        terminal = self.app.query_one("#terminal")
        for pane in self.app.panes:
            record = getattr(self.app, "_agent_headers", {}).get(pane.id)
            if not record or record["state"] != "active":
                continue
            if pane.y > 0:
                terminal.refresh(Region(pane.x, pane.y - 1, pane.width, 1))
            point = pointer_cell(record, pane)
            if point:
                terminal.refresh(Region(*point, 1, 1))

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
                for record in (before, after):
                    point = pointer_cell(record, pane)
                    if point:
                        terminal.refresh(Region(point[0], point[1], 1, 1))
        self.last_frame = frame
