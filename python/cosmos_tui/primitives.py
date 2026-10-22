"""Host independent compact UI primitives. A host paints cells and routes actions.

These objects never write stdout or own a terminal. Textual is one adapter; IME
and Mod presenters can share the same cell/action contract and compositor.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CellRun:
    text: str
    foreground: str
    background: str


@dataclass(frozen=True)
class CompactAction:
    label: str
    width: int = 3

    def paint(self, palette, *, active=False, disabled=False):
        from rich.cells import set_cell_size

        return CellRun(
            set_cell_size(self.label.center(self.width), self.width),
            palette["mute"]
            if disabled
            else palette["on"]
            if active
            else palette["accl"],
            palette["acc"] if active and not disabled else palette["base"],
        )

    def hit(self, x, y):
        return y == 0 and 0 <= x < self.width
