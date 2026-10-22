"""Compact pop-window action selector; shared by narrow cover UIs and notices."""

from textual.binding import Binding
from textual.widgets import Static

from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.zones import Zone


class CompactMenu(CosmosModal):
    zone = Zone.POP_WINDOW
    DEFAULT_CSS = "CompactMenu { align: center middle; background: transparent; } #compact-menu { width: 34; height: auto; max-width: 90%; }"
    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("left,up", "cycle(-1)", show=False),
        Binding("right,down", "cycle(1)", show=False),
        Binding("enter", "choose", show=False),
    ]

    def __init__(self, title, choices):
        super().__init__()
        if not choices:
            raise ValueError("a menu needs at least one enabled choice")
        self.title_text, self.choices, self.index = title, choices, 0

    def compose(self):
        with Frame(id="compact-menu") as box:
            box.border_title = self.title_text
            yield Static("", id="compact-options")

    def on_mount(self):
        self.redraw()

    def redraw(self):
        self.query_one(Static).update(
            "\n".join(
                ("› " if i == self.index else "  ") + label
                for i, (_, label) in enumerate(self.choices)
            )
        )

    def action_cycle(self, direction):
        self.index = (self.index + direction) % len(self.choices)
        self.redraw()

    def action_choose(self):
        self.dismiss(self.choices[self.index][0])

    def action_close(self):
        self.dismiss(None)
