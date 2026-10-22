"""Shared compact controls and btop-like framed panels."""

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.containers import Vertical
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget

from cosmos_tui.ui.cells import cell_width
from cosmos_tui.ui.primitives import CompactAction

DEFAULT = dict(
    bg="#14161e",
    base="#1e212c",
    fg="#cdd2dc",
    mute="#7a8092",
    acc="#62a0e6",
    accl="#a0cdfa",
    on="#10121a",
)


def frame_border(width, palette, label=None, *, top=True, joints=()):
    """Shared folded border for widget popups and RPC Mod popups."""
    label = (label or Text()).copy()
    if width < 2:
        return Text(" " * max(0, width))
    line = Text(
        ("╭" if top else "╰") + "─" * (width - 2) + ("╮" if top else "╯"),
        style=Style(color=palette["acc"], bgcolor=palette["base"]),
    )
    if top and label.plain:
        room = min(joints, default=width - 1) - 5
        label.truncate(max(0, room), overflow="ellipsis")
        if label.plain:
            folded = Text("┐ ", style=line.style) + label + Text(" ┌", style=line.style)
            length = cell_width(folded.plain)
            line = line[:2] + folded + line[2 + length :]
    for x in joints:
        line = line[:x] + Text("┬" if top else "┴", style=line.style) + line[x + 1 :]
    return line


class Frame(Vertical):
    heading_command = None
    junction_selector = None
    DEFAULT_CSS = """
    Frame { border: round #62a0e6; border-title-color: #a0cdfa; background: #1e212c; padding: 0 1; }
    """

    def on_mount(self):
        self.apply_theme(getattr(self.app, "role_colors", DEFAULT))

    def set_heading(self, label, command=None):
        self.border_title = label
        self.heading_command = command
        self.refresh()

    def heading(self, palette):
        from cosmos_tui.input.keymap import COMMANDS, bindings

        text = Text(str(self.border_title or ""), style=palette["fg"])
        command = next((c for c in COMMANDS if c.id == self.heading_command), None)
        if command:
            keys = bindings(command, getattr(self.app, "settings", {}))
            from cosmos_tui.input.keymap import display_binding

            trigger = next(
                (k.split("+")[-1] for k in keys if len(k.split("+")[-1]) == 1), None
            )
            index = text.plain.casefold().find(trigger.casefold()) if trigger else -1
            if index >= 0:
                text.stylize(Style(color=palette["accl"], bold=True), index, index + 1)
            elif keys:
                text.append(
                    " ["
                    + display_binding(keys[0], getattr(self.app, "settings", {}))
                    + "]",
                    style=palette["mute"],
                )
        return text

    def border_strip(self, top):
        palette = getattr(self.app, "role_colors", DEFAULT)
        width = self.region.width
        if width < 2:
            return Strip.blank(width)
        joints = []
        if self.junction_selector:
            for widget in self.query(self.junction_selector):
                x = widget.region.x - self.region.x
                if 0 < x < width - 1:
                    joints.append(x)
        line = frame_border(
            width, palette, self.heading(palette), top=top, joints=joints
        )
        return Strip(
            (
                Segment(
                    s.text,
                    s.style or Style(color=palette["acc"], bgcolor=palette["base"]),
                )
                for s in line.render(self.app.console, end="")
                if s.text and s.text != "\n"
            ),
            width,
        )

    def render_lines(self, crop):
        lines = super().render_lines(crop)
        for i, y in enumerate(crop.line_range):
            if y in (0, self.region.height - 1):
                strip = self.border_strip(y == 0).crop(crop.x, crop.right)
                for line_filter in self.get_line_filters():
                    strip = strip.apply_filter(line_filter, self.background_colors[1])
                lines[i] = strip
        return lines

    def apply_theme(self, palette):
        if getattr(self, "_frame_palette", None) == palette:
            return
        self._frame_palette = palette
        self.styles.border = ("round", palette["acc"])
        self.styles.border_title_color = palette["accl"]
        self.styles.background = palette["base"]
        self.styles.color = palette["fg"]
        for widget in self.query("ListView, Input"):
            widget.styles.background = palette["base"]
            widget.styles.background_tint = "transparent"
            widget.styles.color = palette["fg"]


class MiniAction(Widget, can_focus=True):
    """Textual adapter for Cosmos cell primitives, without Button box styling."""

    DEFAULT_CSS = """
    MiniAction, #assistant-row MiniAction { width: 3; min-width: 3; height: 1; min-height: 1; border: none !important; padding: 0; margin: 0; }
    """

    class Pressed(Message):
        def __init__(self, button):
            super().__init__()
            self.button = button

    def __init__(self, label, **kwargs):
        super().__init__(**kwargs)
        self.primitive = CompactAction(label)
        self.palette = DEFAULT

    def apply_theme(self, palette):
        self.palette = palette
        self.refresh()

    def render(self):
        run = self.primitive.paint(
            self.palette,
            active=self.mouse_hover or self.has_focus,
            disabled=self.disabled,
        )
        return Text(run.text, style=f"{run.foreground} on {run.background}")

    def on_click(self, event):
        if not self.disabled and self.primitive.hit(event.x, event.y):
            event.stop()
            self.post_message(self.Pressed(self))

    def on_key(self, event):
        if event.key in ("enter", "space") and not self.disabled:
            event.stop()
            event.prevent_default()
            self.post_message(self.Pressed(self))

    def on_enter(self):
        self.refresh()

    def on_leave(self):
        self.refresh()

    def on_focus(self):
        self.refresh()

    def on_blur(self):
        self.refresh()


class BottomSheet(Frame):
    """Compact overlay: title separator only, with a separate right-edge shadow."""

    DEFAULT_CSS = """
    BottomSheet { border: none; border-top: solid #62a0e6; padding: 0 1; }
    """

    def apply_theme(self, palette):
        self.styles.border = ("none", palette["acc"])
        self.styles.border_top = ("solid", palette["acc"])
        self.styles.background = palette["base"]
        self.styles.color = palette["fg"]

    def border_strip(self, top=True):
        palette = getattr(self.app, "role_colors", DEFAULT)
        width = self.region.width
        title = self.heading(palette)
        title.truncate(max(0, width - 4), overflow="ellipsis")
        line = Text("─ ", style=Style(color=palette["acc"], bgcolor=palette["base"]))
        line += title
        line.append(" " + "─" * max(0, width - title.cell_len - 3))
        return Strip(list(line.render(self.app.console, end="")), width)

    def render_lines(self, crop):
        # Bypass Frame's closed-box bottom and corner rendering.
        lines = Vertical.render_lines(self, crop)
        if crop.y == 0 and lines:
            strip = self.border_strip().crop(crop.x, crop.right)
            for line_filter in self.get_line_filters():
                strip = strip.apply_filter(line_filter, self.background_colors[1])
            lines[0] = strip
        return lines


class SheetShadow(Widget):
    """One-cell textured shadow on a sheet's right edge."""

    DEFAULT_CSS = """
    SheetShadow { position: absolute; width: 1; background: transparent; }
    """

    def place(self, sheet, x, y, width, height, *, contained=False):
        # Reserve a single column when the sheet touches the screen edge.
        content_width = max(
            1, width - int(contained or x + width >= self.app.size.width)
        )
        sheet.styles.width, sheet.styles.height = content_width, height
        sheet.styles.offset = (x, y)
        self.styles.offset = (x + content_width, y + 1)
        self.styles.height = max(1, height - 1)
        self.display = x + content_width < self.app.size.width and height > 1

    def render_line(self, y):
        from cosmos_tui.ui.theme import blend

        palette = getattr(self.app, "role_colors", DEFAULT)
        style = Style(
            color=blend(palette["bg"], palette["mute"], 0.35), bgcolor=palette["bg"]
        )
        return Strip([Segment("░" * self.size.width, style)], self.size.width)
