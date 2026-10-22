from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.styles import DARK
from cosmos_tui.ui.keyboard import KeyboardPreview


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
            yield KeyboardPreview(
                [part for key, _ in self.items for part in key.split(" / ")]
            )

    def on_mount(self):
        self.fit_keyboard()

    def on_resize(self):
        if self.is_mounted:
            self.fit_keyboard()

    def fit_keyboard(self):
        self.query_one(KeyboardPreview).fit(minimum_height=(len(self.items) + 15) * 10 // 9 + 1)
