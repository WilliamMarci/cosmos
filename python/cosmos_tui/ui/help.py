from __future__ import annotations

from rich.text import Text
from rich.style import Style
from textual.binding import Binding
from textual.widgets import Static, ListView, ListItem, Label

from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.styles import DARK
from cosmos_tui.ui.keyboard import KeyboardPreview, key_legend
from cosmos_tui.ui.cells import cell_width


class Help(CosmosModal):
    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("question_mark", "dismiss", show=False),
    ]
    DEFAULT_CSS = """
    #help-list { height: 1fr; min-height: 3; margin: 0; }
    #key-legend { height: 1; }
    """

    def __init__(self, title, items):
        super().__init__()
        self.heading, self.items = title, items

    def compose(self):
        palette = getattr(self.app, "role_colors", DARK)
        with Frame(id="help-frame") as frame:
            frame.set_heading(self.heading, "workspace.help")
            listing = ListView(id="help-list")
            listing.styles.margin = 0
            yield listing
            yield Static(key_legend(palette), id="key-legend")
            yield KeyboardPreview()

    async def on_mount(self):
        palette = getattr(self.app, "role_colors", DARK)
        rows = []
        column = min(
            max((cell_width(key) + 2 for key, _ in self.items), default=19),
            max(19, self.app.size.width // 3),
        )
        for key, label in self.items:
            text = Text(key, style="bold " + palette["accl"])
            text.truncate(column - 2, overflow="ellipsis")
            text.pad_right(max(0, column - text.cell_len))
            text.append(label, style=Style(color=palette["fg"], bold=False))
            rows.append(ListItem(Label(text)))
        await self.query_one(ListView).extend(rows)
        self.query_one(ListView).index = 0 if rows else None
        self.fit_keyboard()
        self.query_one(ListView).focus()
        self.update_keyboard()

    def on_list_view_highlighted(self, event):
        self.update_keyboard()

    def update_keyboard(self):
        index = self.query_one(ListView).index
        keys = (
            self.items[index][0].split(" / ")
            if index is not None and index < len(self.items)
            else []
        )
        self.query_one(KeyboardPreview).present(keys)

    def on_resize(self):
        if self.is_mounted:
            self.fit_keyboard()

    def fit_keyboard(self):
        self.query_one("#help-frame").styles.height = max(
            6, int(self.app.size.height * 0.85)
        )
        self.query_one(KeyboardPreview).fit(minimum_height=24)
        self.query_one("#key-legend").display = self.query_one(KeyboardPreview).display

    def on_key(self, event):
        if event.key in ("home", "end", "pageup", "pagedown"):
            listing = self.query_one(ListView)
            if self.items:
                old = listing.index or 0
                page = max(1, listing.size.height - 1)
                listing.index = (
                    0
                    if event.key == "home"
                    else len(self.items) - 1
                    if event.key == "end"
                    else max(
                        0,
                        min(
                            len(self.items) - 1,
                            old + (page if event.key == "pagedown" else -page),
                        ),
                    )
                )
            event.stop()
            event.prevent_default()
