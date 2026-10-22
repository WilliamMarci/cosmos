"""Compact setting rows: label left, current value and cycle arrows right."""

from rich.text import Text
from textual.message import Message
from textual.widget import Widget


class SettingRow(Widget):
    DEFAULT_CSS = "SettingRow { height: 1; width: 100%; background: transparent; }"

    class Cycle(Message):
        def __init__(self, row, direction):
            super().__init__()
            self.row, self.direction = row, direction

    def __init__(self, row):
        super().__init__()
        self.row = row
        self.arrows = None

    def render(self):
        palette = self.app.role_colors
        row = self.row
        left = Text(row["label"])
        right = Text()
        if row.get("choices"):
            label = next(
                (label for value, label in row["choices"] if value == row["value"]),
                str(row["value"]),
            )
            right.append("◂ ", style=palette["accl"])
            right.append(label)
            right.append(" ▸", style=palette["accl"])
        elif row.get("hint"):
            right.append(row["hint"], style=palette["mute"])
        width = self.size.width
        right.truncate(max(0, width // 2), overflow="ellipsis")
        left.truncate(max(0, width - right.cell_len - 2), overflow="ellipsis")
        left.pad_right(max(0, width - right.cell_len - left.cell_len))
        self.arrows = (
            (width - right.cell_len, width - 1) if row.get("choices") else None
        )
        return left + right

    def on_click(self, event):
        if self.arrows and event.x >= self.arrows[0]:
            event.stop()
            self.post_message(
                self.Cycle(self.row, -1 if event.x == self.arrows[0] else 1)
            )
