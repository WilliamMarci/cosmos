"""Quiet session/window picker with pane previews matching the backend layout."""

import asyncio
from .surfaces import Zone
from .terminal_grid import decode_grid
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from .chrome import Frame
from .shortcuts import CosmosInput, CosmosModal
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Static


class LayoutPreview(Widget):
    def __init__(self):
        super().__init__()
        self.panes = []

    def render_line(self, y):
        colors = self.app.role_colors
        width = self.size.width
        height = max(1, self.size.height)
        base = Style(color=colors["mute"], bgcolor=colors["base"])
        strip = Strip([Segment(" " * width, base)], width)
        if not self.panes:
            return strip
        sw = max(p.x + p.width for p in self.panes)
        sh = max(p.y + p.height for p in self.panes)
        for pane in self.panes:
            x = int(pane.x * width / sw)
            end = min(width, max(x + 1, int((pane.x + pane.width) * width / sw)))
            top = int(pane.y * height / sh)
            bottom = min(
                height, max(top + 1, int((pane.y + pane.height) * height / sh))
            )
            if not top <= y < bottom:
                continue
            if y == top:
                style = Style(
                    color=colors["on"] if pane.active else colors["fg"],
                    bgcolor=colors["acc"] if pane.active else colors["base"],
                    bold=pane.active,
                )
                text = Text(" " + pane.id, style=style)
            else:
                style = Style(color=colors["fg"], bgcolor=colors["bg"])
                row = y - top - 1
                text = (
                    decode_grid(tuple(pane.lines))[row].copy()
                    if row < len(pane.lines)
                    else Text("")
                )
                text.stylize_before(style)
            content = (
                Strip(
                    Segment(s.text, s.style or style, s.control)
                    for s in text.render(self.app.console, end="")
                )
                .crop(0, end - x)
                .extend_cell_length(end - x, style)
            )
            strip = Strip.join(
                [strip.crop(0, x), content, strip.crop(end, width)]
            ).crop(0, width)
        return strip


class Switcher(CosmosModal):
    zone = Zone.POP_WINDOW
    AUTO_FOCUS = "#switch-filter"
    BINDINGS = [Binding("escape", "cancel", show=False)]
    DEFAULT_CSS = """
    Switcher { align: center middle; background: transparent; }
    #switcher { width: 88%; height: 82%; }
    #switch-columns { height: 1fr; }
    #switch-browser { width: 35%; min-width: 12; height: 100%; border-right: solid #7a8092; padding-right: 1; }
    #switch-list { height: 1fr; min-height: 2; background: #1e212c; margin-top: 1; }
    LayoutPreview { width: 1fr; height: 100%; margin-left: 1; background: #14161e; }
    #switch-error { height: auto; color: #eb7080; }
    """

    def __init__(self):
        super().__init__()
        self.inventory_ready = asyncio.Event()
        self.windows = []
        self.rows = []
        self.pending = None
        self.preview_busy = False
        self.revision = 0
        self.filter_query = None

    def compose(self):
        with Frame(id="switcher") as frame:
            frame.border_title = "Switch"
            with Horizontal(id="switch-columns"):
                with Vertical(id="switch-browser"):
                    yield CosmosInput(id="switch-filter")
                    listing = ListView(id="switch-list")
                    listing.can_focus = False
                    yield listing
                yield LayoutPreview()
            yield Static("", id="switch-error")

    async def on_mount(self):
        self.set_focus(self.query_one(Input))
        try:
            self.windows = await self.app.backend.inventory()
            await self.populate()
            self.set_focus(self.query_one(Input))
            self.set_interval(0.15, self.refresh_preview)
        except Exception as error:
            self.error(error)
        finally:
            self.inventory_ready.set()

    def error(self, error):
        self.query_one("#switch-error", Static).update(Text(str(error)))

    async def populate(self):
        query = self.query_one(Input).value.casefold()
        selected = self.selected()
        previous = (
            selected["window_id"]
            if selected
            else next((t[0] for t in self.app.backend.tabs if t[2] == "1"), None)
        )
        self.rows = [
            w
            for w in self.windows
            if query in f"{w['session']} {w['index']} {w['name']}".casefold()
        ]
        listing = self.query_one(ListView)
        await listing.clear()
        await listing.extend(
            ListItem(Label(Text(f"{w['session']}  /  {w['index']} {w['name']}")))
            for w in self.rows
        )
        self.filter_query = query
        self.revision += 1
        if self.rows:
            listing.index = next(
                (i for i, w in enumerate(self.rows) if w["window_id"] == previous), 0
            )
            self.pending = self.rows[listing.index]["window_id"]
        else:
            self.pending = None
            preview = self.query_one(LayoutPreview)
            preview.panes = []
            preview.refresh()

    def selected(self):
        listing = self.query_one(ListView)
        index = listing.index
        return (
            self.rows[index]
            if index is not None and 0 <= index < len(self.rows)
            else None
        )

    def on_input_changed(self, event):
        # The timer coalesces rapid typing; do not rebuild children in a key event.
        pass

    def on_list_view_highlighted(self, event):
        selected = self.selected()
        self.pending = selected["window_id"] if selected else None

    async def refresh_preview(self):
        if self.query_one(Input).value.casefold() != self.filter_query:
            await self.populate()
        if self.preview_busy or self.pending is None or self.app.screen is not self:
            return
        self.preview_busy = True
        target = self.pending
        revision = self.revision
        try:
            panes = await self.app.backend.snapshot(target)
            if self.pending == target and self.revision == revision and self.is_mounted:
                preview = self.query_one(LayoutPreview)
                if preview.panes != panes:
                    preview.panes = panes
                    preview.refresh()
        except Exception as error:
            if self.is_mounted:
                self.error(error)
        finally:
            self.preview_busy = False

    async def on_key(self, event: events.Key):
        field = self.query_one(Input)
        if self.focused is not field:
            self.set_focus(field)
            if event.character and event.character.isprintable():
                field.value += event.character
                field.cursor_position = len(field.value)
                event.stop()
                event.prevent_default()
                return
            if event.key == "enter":
                await self.confirm()
                event.stop()
                event.prevent_default()
                return
        if event.key in ("up", "down"):
            listing = self.query_one(ListView)
            if self.rows:
                listing.index = max(
                    0,
                    min(
                        len(self.rows) - 1,
                        (listing.index or 0) + (1 if event.key == "down" else -1),
                    ),
                )
            event.stop()
            event.prevent_default()

    async def on_input_submitted(self, event):
        await self.confirm()

    async def on_list_view_selected(self, event):
        await self.confirm()

    async def confirm(self):
        # Input submission may race the inventory read or ListView child rebuild.
        # Resolve stable IDs from the filter, without awaiting UI selection changes.
        await self.inventory_ready.wait()
        query = self.query_one(Input).value.casefold()
        matches = [
            w
            for w in self.windows
            if query in f"{w['session']} {w['index']} {w['name']}".casefold()
        ]
        selected = self.selected()
        if selected not in matches:
            selected = matches[0] if matches else None
        if not selected:
            return
        try:
            await self.app.backend.select_window(selected)
            self.dismiss()
        except Exception as error:
            self.error(error)
            self.windows = await self.app.backend.inventory()
            await self.populate()

    def action_cancel(self):
        self.dismiss()
