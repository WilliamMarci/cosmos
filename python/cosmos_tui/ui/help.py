from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.styles import DARK


class Help(CosmosModal):
    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("question_mark", "dismiss", show=False),
    ]

    def __init__(self, title, items):
        super().__init__()
        self.heading = title
        self.items = items

    def compose(self):
        palette = getattr(self.app, "role_colors", DARK)
        text = Text()
        for key, label in self.items:
            text.append(f"{key:<19}", style="bold " + palette["accl"])
            text.append(label + "\n", style=palette["fg"])
        with Frame(id="help-frame") as frame:
            frame.set_heading(self.heading, "workspace.help")
            yield Static(text, id="help-content")
