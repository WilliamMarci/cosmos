"""Shared compact controls and btop-like framed panels."""

from textual.containers import Vertical
from textual.widget import Widget
from textual.message import Message
from rich.text import Text
from .primitives import CompactAction

DEFAULT = dict(
    bg="#14161e",
    base="#1e212c",
    fg="#cdd2dc",
    mute="#7a8092",
    acc="#62a0e6",
    accl="#a0cdfa",
    on="#10121a",
)


class Frame(Vertical):
    DEFAULT_CSS = """
    Frame { border: round #62a0e6; border-title-color: #a0cdfa; background: #1e212c; padding: 0 1; }
    """

    def on_mount(self):
        self.apply_theme(getattr(self.app, "role_colors", DEFAULT))

    def apply_theme(self, palette):
        if getattr(self, "_frame_palette", None) == palette:
            return
        self._frame_palette = palette
        self.styles.border = ("round", palette["acc"])
        self.styles.border_title_color = palette["accl"]
        self.styles.background = palette["base"]
        self.styles.color = palette["fg"]


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
