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
