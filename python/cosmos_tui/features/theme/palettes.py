"""Terminal colors are independent of interface roles; truecolor stays explicit."""

from rich.color import Color, ColorType
from rich.style import Style
from cosmos_tui.ui.styles import DARK, LIGHT

TERMINALS = [
    ("inherit", "Follow terminal"),
    ("ubuntu", "Ubuntu · Tango"),
    ("cosmos-dark", "Cosmos Dark"),
    ("cosmos-light", "Cosmos Light"),
]
INTERFACES = [("dark", "Cosmos Dark"), ("light", "Cosmos Light")]
TANGO = [
    "#2e3436",
    "#cc0000",
    "#4e9a06",
    "#c4a000",
    "#3465a4",
    "#75507b",
    "#06989a",
    "#d3d7cf",
    "#555753",
    "#ef2929",
    "#8ae234",
    "#fce94f",
    "#729fcf",
    "#ad7fa8",
    "#34e2e2",
    "#eeeeec",
]


def terminal_palette(name):
    if name == "inherit":
        return dict(fg="default", bg="default", ansi=None)
    if name == "ubuntu":
        return dict(fg="#eeeeec", bg="#300a24", ansi=TANGO)
    palette = LIGHT if name == "cosmos-light" else DARK
    return dict(fg=palette["fg"], bg=palette["bg"], ansi=TANGO)


def terminal_style(style, palette):
    if style is None:
        style = Style()

    def resolve(color, default):
        if color is None or color.type == ColorType.DEFAULT:
            return Color.parse(palette[default])
        if (
            palette["ansi"]
            and color.type in (ColorType.STANDARD, ColorType.EIGHT_BIT)
            and color.number is not None
            and color.number < 16
        ):
            return Color.parse(palette["ansi"][color.number])
        return color

    return style + Style(
        color=resolve(style.color, "fg"), bgcolor=resolve(style.bgcolor, "bg")
    )
