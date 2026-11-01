"""Shared solid-color blocks and adjoining-background separators."""

from rich.text import Text
from rich.style import Style


def transition(style, before, after, direction="right"):
    """Join actual neighboring background colors, including gradient endpoints."""
    if style == "none":
        return Text()
    if style == "capsule":
        glyph = "" if direction == "left" else ""
    elif style == "powerline":
        glyph = "" if direction == "left" else ""
    else:
        glyph = "│" if style == "vertical" else "╲" if direction == "left" else "╱"
    foreground, background = (after, before) if direction == "left" else (before, after)
    return Text(glyph, style=Style(color=foreground, bgcolor=background))


def color_block(label, foreground, background):
    return Text(" " + label + " ", style=Style(color=foreground, bgcolor=background))


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def gradient_block(label, foreground, background):
    """Render the padded COSMOS-style label across two color gradients."""
    title = " " + label + " "
    begin, end = (_rgb(color) for color in foreground)
    dark_begin, dark_end = (_rgb(color) for color in background)
    start = Text()
    for index, character in enumerate(title):
        fraction = max(0, min(1, (index - 1) / max(1, len(label) - 1)))
        color = "#%02x%02x%02x" % tuple(
            round(a + (b - a) * fraction) for a, b in zip(begin, end)
        )
        background_color = "#%02x%02x%02x" % tuple(
            round(a + (b - a) * fraction) for a, b in zip(dark_begin, dark_end)
        )
        start.append(
            character,
            style=Style(color=color, bgcolor=background_color, bold=True),
        )
    return start
