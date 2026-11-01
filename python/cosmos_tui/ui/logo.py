"""Theme-rendered COSMOS wordmark using the frozen pagga glyphs."""

from __future__ import annotations

from dataclasses import dataclass
import math
from functools import lru_cache
import unicodedata

from rich.text import Text

from cosmos_tui.core.paths import ASSET_DIR

MODES = ("vertical", "horizontal", "diagonal", "radial")
RESET = "\x1b[0m"


@dataclass(frozen=True)
class LogoStyle:
    foreground: tuple[str, str]
    background: tuple[str, str]
    mode: str = "diagonal"
    steps: int = 8

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError("logo mode must be vertical, horizontal, diagonal or radial")
        if not 2 <= int(self.steps) <= 256:
            raise ValueError("logo steps must be between 2 and 256")


DEFAULT_LOGO = LogoStyle(
    foreground=("#FFE6A3", "#16966A"),
    background=("#3A3120", "#103027"),
    mode="diagonal",
    steps=8,
)


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _width(character):
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1


def _position(mode, x, y, width, height):
    nx = x / max(1, width - 1)
    ny = y / max(1, height - 1)
    if mode == "vertical":
        return ny
    if mode == "horizontal":
        return nx
    if mode == "diagonal":
        return (nx + ny) / 2
    dx = (nx - 0.5) * 2 if width > 1 else 0
    dy = (ny - 0.5) * 2 if height > 1 else 0
    axes = int(width > 1) + int(height > 1)
    return min(1, math.hypot(dx, dy) / math.sqrt(max(1, axes)))


def _interpolate(start, end, fraction, steps):
    fraction = max(0, min(1, fraction))
    level = int(fraction * (steps - 1) + 0.5)
    fraction = level / (steps - 1)
    return tuple(
        int(a + (b - a) * fraction + 0.5) for a, b in zip(start, end)
    )


@lru_cache(maxsize=1)
def logo_lines():
    return tuple(
        Text.from_ansi((ASSET_DIR / "cosmos-logo.ansi").read_text()).plain.splitlines()
    )


@lru_cache(maxsize=32)
def render_logo(style: LogoStyle) -> str:
    """Return ANSI text for the frozen glyphs with a themed gradient."""
    lines = logo_lines()
    width = max(sum(_width(ch) for ch in line) for line in lines)
    height = len(lines)
    start, end = _rgb(style.foreground[0]), _rgb(style.foreground[1])
    output = []
    for y, line in enumerate(lines):
        chunks = []
        current = None
        x = 0
        for character in line:
            size = _width(character)
            if character == " ":
                chunks.append(character)
            else:
                fraction = _position(style.mode, x, y, width, height)
                color = _interpolate(start, end, fraction, int(style.steps))
                if color != current:
                    chunks.append(f"\x1b[38;2;{color[0]};{color[1]};{color[2]}m")
                    current = color
                chunks.append(character)
            x += size
        output.append("".join(chunks) + RESET)
    return "\n".join(output) + "\n"


def render_logo_text(style: LogoStyle) -> Text:
    return Text.from_ansi(render_logo(style))
