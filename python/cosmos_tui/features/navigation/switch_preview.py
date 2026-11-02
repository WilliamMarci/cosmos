"""Pane layout previews for Switch; stable IDs back click targets."""

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip
from textual.widget import Widget
from textual.message import Message
from cosmos_tui.render.ansi import decode_grid


class LayoutPreview(Widget):
    class Chosen(Message):
        def __init__(self, pane):
            super().__init__()
            self.pane = pane

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
                text = Text(f" {pane.index} {pane.name}", style=style)
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

    def on_click(self, event):
        if not self.panes:
            return
        sw = max(p.x + p.width for p in self.panes)
        sh = max(p.y + p.height for p in self.panes)
        for pane in self.panes:
            left = int(pane.x * self.size.width / sw)
            right = max(left + 1, int((pane.x + pane.width) * self.size.width / sw))
            top = int(pane.y * self.size.height / sh)
            bottom = max(top + 1, int((pane.y + pane.height) * self.size.height / sh))
            if left <= event.x < right and top <= event.y < bottom:
                event.stop()
                self.post_message(self.Chosen(pane.id))
                break


class SwitchDivider(Widget):
    DEFAULT_CSS = "SwitchDivider { width: 1; height: 100%; }"

    def render_line(self, y):
        palette = self.app.role_colors
        return Strip(
            [Segment("│", Style(color=palette["acc"], bgcolor=palette["base"]))], 1
        )

    # Divider has no input behavior.
