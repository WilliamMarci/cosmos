"""Terminal colors are independent of interface roles; truecolor stays explicit."""

from rich.color import Color, ColorType
from rich.style import Style

from cosmos_tui.features.theme.catalog import terminal_theme


def terminal_palette(name):
    theme = terminal_theme(name)
    if theme is None or theme.ansi is None:
        return dict(fg="default", bg="default", ansi=None)
    return dict(fg=theme.fg, bg=theme.bg, ansi=theme.ansi)


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
