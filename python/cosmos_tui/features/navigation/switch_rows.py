"""Compact tree rows: controls appear on selection or hover, with cell hit regions."""

from rich.text import Text
from textual.widget import Widget
from textual.message import Message
from cosmos_tui.ui.primitives import CompactAction


class SwitchRow(Widget):
    DEFAULT_CSS = "SwitchRow { height: 1; width: 100%; }"

    class Action(Message):
        def __init__(self, row, action):
            super().__init__()
            self.row = row
            self.action = action

    def __init__(self, row, expanded):
        super().__init__()
        self.row = row
        self.expanded = expanded
        self.hovered = False
        self.hits = []

    def render(self):
        palette = self.app.role_colors
        active = bool(getattr(self.parent, "highlighted", False))
        bg = palette["acc"] if active else palette["base"]
        fg = palette["on"] if active else palette["fg"]
        controls = Text()
        self.hits = []
        show = active or self.hovered
        level = {"session": 0, "window": 1, "pane": 2}[self.row["kind"]]
        prefix = "  " * level
        arrow = ("▾" if self.expanded else "▸") if level < 2 else " "
        row = self.row
        label = (
            f"{row['session_id']} {row['session']}"
            if level == 0
            else f"{row['index']} {row['name']} {row['window_id']}"
            if level == 1
            else f"{row['pane_index']} {row.get('pane_name') or row.get('program') or 'pane'} {row['pane_id']}"
        )
        left = Text(prefix + arrow + " " + label, style=f"{fg} on {bg}")
        if level < 2:
            self.hits.append((len(prefix), len(prefix) + 1, "fold"))
        if show:
            for name, glyph in (("switch", "↵"), ("rename", "✎"), ("more", "⋯")):
                paint = CompactAction(glyph).paint(palette)
                controls.append(
                    paint.text, style=f"{paint.foreground} on {paint.background}"
                )
        room = max(0, self.size.width - controls.cell_len)
        left.truncate(room, overflow="ellipsis")
        left.pad_right(max(0, room - left.cell_len))
        if show:
            self.hits.extend(
                (room + i * 3, room + (i + 1) * 3, name)
                for i, name in enumerate(("switch", "rename", "more"))
            )
        return left + controls

    def on_enter(self):
        self.hovered = True
        self.refresh()

    def on_leave(self):
        self.hovered = False
        self.refresh()

    def on_click(self, event):
        action = next((name for x, end, name in self.hits if x <= event.x < end), None)
        if action:
            event.stop()
            self.post_message(self.Action(self.row, action))
