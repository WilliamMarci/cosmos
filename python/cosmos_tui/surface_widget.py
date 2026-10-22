"""Textual host for shared cell frames; renderer and actions stay host-independent."""

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget
from textual.geometry import Region
from .ui import clip, cell_width


class CellSurface(Widget):
    DEFAULT_CSS = "CellSurface { position: absolute; border: none; padding: 0; margin: 0; background: transparent; }"

    def __init__(self, registry, owner, **kwargs):
        super().__init__(**kwargs)
        self.registry, self.owner = registry, owner
        self.frame = None
        self.pressed = None

    def present(self, frame):
        previous = self.frame
        self.frame = frame
        self.registry.submit(self.owner, frame)
        rect = frame.bounds
        if not previous or previous.bounds != rect:
            self.styles.width, self.styles.height = rect.width, rect.height
            self.styles.offset = rect.x, rect.y
            self.refresh(layout=True)
        elif (frame.runs, frame.hits) != (previous.runs, previous.hits):
            if frame.dirty:
                for dirty in frame.dirty:
                    self.refresh(
                        Region(
                            dirty.x - rect.x,
                            dirty.y - rect.y,
                            dirty.width,
                            dirty.height,
                        )
                    )
            else:
                self.refresh()

    def render_line(self, y):
        width = self.size.width
        strip = (
            self.app.render_background(self.frame.bounds, y)
            if self.frame and hasattr(self.app, "render_background")
            else Strip.blank(width, Style())
        )
        if not self.frame:
            return strip
        bounds = self.frame.bounds
        for run in self.frame.runs:
            if run.rect.y - bounds.y != y:
                continue
            x = run.rect.x - bounds.x
            text = clip(run.text, run.rect.width)
            text += " " * max(0, run.rect.width - cell_width(text))
            part = Strip(
                [
                    Segment(
                        text,
                        Style(
                            color=run.foreground, bgcolor=run.background, bold=run.bold
                        ),
                    )
                ]
            )
            strip = Strip.join(
                [strip.crop(0, x), part, strip.crop(x + run.rect.width, width)]
            )
        return strip

    def on_mouse_down(self, event):
        if event.button == 1 and self.frame:
            self.pressed = self.frame.hit(event.screen_x, event.screen_y)
            event.stop()

    def on_mouse_up(self, event):
        if event.button == 1 and self.frame:
            released = self.frame.hit(event.screen_x, event.screen_y)
            if released and released == self.pressed:
                self.registry.dispatch(self.owner, event.screen_x, event.screen_y)
            self.pressed = None
            event.stop()
