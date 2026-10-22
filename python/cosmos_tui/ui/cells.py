"""Shared cell UI contract for all seven zones; no terminal or Textual ownership."""

from dataclasses import dataclass
from typing import Callable

import regex
from wcwidth import wcswidth

from cosmos_tui.ui.zones import Zone


def clusters(text):
    return list(regex.finditer(r"\X", text))


def cell_width(text):
    return sum(max(0, wcswidth(m.group())) for m in clusters(text))


def boundaries(text):
    return [0] + [m.end() for m in clusters(text)]


def snap(text, position):
    return max((p for p in boundaries(text) if p <= position), default=0)


def clip(text, width):
    result, cells = "", 0
    for match in clusters(text):
        size = max(0, wcswidth(match.group()))
        if cells + size > width:
            break
        result += match.group()
        cells += size
    return result


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int = 1

    def contains(self, x, y):
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def intersects(self, other):
        return (
            self.x < other.x + other.width
            and other.x < self.x + self.width
            and self.y < other.y + other.height
            and other.y < self.y + self.height
        )


@dataclass(frozen=True)
class CellRun:
    rect: Rect
    text: str
    foreground: str
    background: str
    bold: bool = False


@dataclass(frozen=True)
class HitRegion:
    action: str
    rect: Rect
    enabled: bool = True


@dataclass(frozen=True)
class UIFrame:
    bounds: Rect
    runs: tuple[CellRun, ...] = ()
    hits: tuple[HitRegion, ...] = ()
    dirty: tuple[Rect, ...] = ()
    cursor: tuple[int, int] | None = None

    def hit(self, x, y):
        return next(
            (r.action for r in self.hits if r.enabled and r.rect.contains(x, y)), None
        )


class UIRegistry:
    """Lifecycle/focus/hit dispatch used by actual presenters, not a plugin sandbox."""

    def __init__(self):
        self.surfaces = {}
        self.focus = None

    def attach(self, owner: str, zone: Zone, action: Callable):
        if owner in self.surfaces:
            raise ValueError("UI owner already attached")
        self.surfaces[owner] = dict(zone=Zone(zone), action=action, frame=None)

    def submit(self, owner, frame):
        self.surfaces[owner]["frame"] = frame

    def activate(self, owner):
        if owner not in self.surfaces:
            raise KeyError(owner)
        self.focus = owner

    def dispatch(self, owner, x, y):
        surface = self.surfaces.get(owner)
        frame = surface and surface["frame"]
        action = frame.hit(x, y) if frame else None
        if action:
            surface["action"](action)
        return action

    def detach(self, owner):
        self.surfaces.pop(owner, None)
        if self.focus == owner:
            self.focus = None
