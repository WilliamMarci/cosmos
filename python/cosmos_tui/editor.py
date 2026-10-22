"""One-row cell editor shared by cover-line presenters (no ANSI output)."""

import re
from textual import events
from textual.message import Message
from textual.widget import Widget
from textual.strip import Strip
from textual.geometry import Region
from rich.segment import Segment
from rich.style import Style
from .ui import clusters, boundaries, cell_width, clip, snap


class CellEditor(Widget, can_focus=True):
    DEFAULT_CSS = "CellEditor { height: 1; border: none; padding: 0; margin: 0; }"

    class Changed(Message):
        def __init__(self, editor):
            super().__init__()
            self.editor = editor

    class Submitted(Message):
        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.value, self.cursor_position, self.anchor = "", 0, 0
        self.start = 0
        self.roles = {}
        self.read_only = False
        self.cursor_blink = True
        self.visible_cursor = True
        self._dragging = False

    def on_mount(self):
        self.blink = self.set_interval(0.5, self._toggle, pause=True)

    def _toggle(self):
        self.visible_cursor = not self.visible_cursor
        self.refresh(Region(self.cursor_cell, 0, max(1, self.cursor_width), 1))

    def update_focus(self):
        if hasattr(self, "blink"):
            if self.has_focus and not self.read_only:
                self.blink.resume()
            else:
                self.blink.pause()
        self.visible_cursor = True
        self.refresh()

    on_focus = update_focus
    on_blur = update_focus

    def assign(self, text, cursor):
        self.value = text
        self.cursor_position = snap(text, max(0, min(len(text), cursor)))
        self.anchor = self.cursor_position
        self.refresh()

    def viewport(self):
        cursor = snap(self.value, self.cursor_position)
        self.start = min(snap(self.value, self.start), cursor)
        while self.start < cursor and cell_width(
            self.value[self.start : cursor]
        ) >= max(1, self.size.width):
            self.start = next(p for p in boundaries(self.value) if p > self.start)
        self.cursor_cell = cell_width(self.value[self.start : cursor])
        current = next(
            (m.group() for m in clusters(self.value) if m.start() == cursor), " "
        )
        self.cursor_width = max(1, cell_width(current))
        if self.cursor_cell + self.cursor_width > self.size.width:
            self.start = cursor
            self.cursor_cell = 0

    def render_line(self, y):
        self.viewport()
        roles = self.roles
        fg, bg = roles.get("text"), roles.get("surface")
        style = Style(color=fg, bgcolor=bg)
        if not self.value:
            text = clip("描述命令…", self.size.width)
            segments = []
            for index, match in enumerate(clusters(text)):
                cursor = (
                    index == 0
                    and self.has_focus
                    and not self.read_only
                    and self.visible_cursor
                )
                segments.append(
                    Segment(
                        match.group(),
                        Style(
                            color=bg if cursor else roles.get("muted"),
                            bgcolor=fg if cursor else bg,
                        ),
                    )
                )
        else:
            segments = []
            position = self.start
            selected = sorted((self.cursor_position, self.anchor))
            for match in clusters(clip(self.value[self.start :], self.size.width)):
                cluster = match.group()
                end = position + len(cluster)
                marked = selected[0] <= position < selected[1]
                cursor = (
                    position == self.cursor_position
                    and self.has_focus
                    and not self.read_only
                    and self.visible_cursor
                )
                segments.append(
                    Segment(
                        cluster,
                        Style(
                            color=bg if marked or cursor else fg,
                            bgcolor=fg if marked or cursor else bg,
                        ),
                    )
                )
                position = end
        strip = Strip(segments).extend_cell_length(self.size.width, style)
        if (
            self.has_focus
            and bool(self.value)
            and not self.read_only
            and self.visible_cursor
            and self.cursor_position == len(self.value)
        ):
            x = min(self.cursor_cell, max(0, self.size.width - 1))
            strip = Strip.join(
                [
                    strip.crop(0, x),
                    Strip([Segment(" ", Style(color=bg, bgcolor=fg))]),
                    strip.crop(x + 1, self.size.width),
                ]
            )
        return strip

    def move(self, position, select=False):
        self.cursor_position = snap(self.value, position)
        if not select:
            self.anchor = self.cursor_position
        self.visible_cursor = True
        self.refresh()

    def insert(self, text):
        if self.read_only:
            return
        start, end = sorted((self.anchor, self.cursor_position))
        self.value = self.value[:start] + text + self.value[end:]
        self.move(start + len(text))
        self.post_message(self.Changed(self))

    def on_paste(self, event: events.Paste):
        event.stop()
        self.insert(re.sub(r"\r\n|\r|\n", " ", event.text))

    def on_key(self, event):
        key = event.key
        if self.read_only:
            event.stop()
            return
        if key in (
            "up",
            "down",
            "tab",
            "shift+tab",
            "escape",
            "ctrl+c",
            "ctrl+q",
            "ctrl+g",
        ):
            return
        points = boundaries(self.value)
        if key in ("left", "shift+left"):
            self.move(
                max((p for p in points if p < self.cursor_position), default=0),
                key.startswith("shift+"),
            )
        elif key in ("right", "shift+right"):
            self.move(
                next((p for p in points if p > self.cursor_position), len(self.value)),
                key.startswith("shift+"),
            )
        elif key in ("home", "ctrl+a", "shift+home"):
            self.move(0, key.startswith("shift+"))
        elif key in ("end", "ctrl+e", "shift+end"):
            self.move(len(self.value), key.startswith("shift+"))
        elif key in ("backspace", "delete"):
            if self.anchor == self.cursor_position:
                self.anchor = (
                    max((p for p in points if p < self.cursor_position), default=0)
                    if key == "backspace"
                    else next(
                        (p for p in points if p > self.cursor_position), len(self.value)
                    )
                )
            self.insert("")
        elif key == "ctrl+u":
            self.anchor = 0
            self.insert("")
        elif key == "ctrl+w":
            prefix = self.value[: self.cursor_position].rstrip()
            self.anchor = snap(self.value, max(prefix.rfind(" ") + 1, 0))
            self.insert("")
        elif key == "enter":
            self.post_message(self.Submitted())
        elif event.character and event.character.isprintable():
            self.insert(event.character)
        else:
            return
        event.stop()
        event.prevent_default()

    def position_at(self, x):
        self.viewport()
        position, cells = self.start, 0
        for match in clusters(self.value[self.start :]):
            width = cell_width(match.group())
            if cells + width > x:
                break
            position += len(match.group())
            cells += width
        return position

    def on_mouse_down(self, event):
        if event.button == 1 and not self.read_only:
            self.focus()
            self.move(self.position_at(event.x))
            self._dragging = True
            self.capture_mouse()
            event.stop()

    def on_mouse_move(self, event):
        if self._dragging:
            self.move(self.position_at(max(0, event.x)), True)
            event.stop()

    def on_mouse_up(self, event):
        if self._dragging:
            self._dragging = False
            self.release_mouse()
            event.stop()

    def on_mouse_scroll_up(self, event):
        event.stop()

    def on_mouse_scroll_down(self, event):
        event.stop()
