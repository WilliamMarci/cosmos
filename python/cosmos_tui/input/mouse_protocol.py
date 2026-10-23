"""Encode pointer events for applications tracking the mouse inside a pane.

Cosmos owns the physical terminal's mouse reporting, so Tmux never sees these
events.  The pointer router uses this module to rebuild the byte sequence the
pane application asked for and hands it to the backend unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cosmos_tui.terminal.tmux import Pane

SHIFT = 4
META = 8
CTRL = 16

LEFT = 0
MIDDLE = 1
RIGHT = 2
WHEEL_UP = 64
WHEEL_DOWN = 65
WHEEL_LEFT = 66
WHEEL_RIGHT = 67

MOTION = 32
RELEASE = 3
LEGACY_MAX = 255 - 32
UTF8_MAX = 2047 - 32


def modifiers(event) -> int:
    return (
        (SHIFT if event.shift else 0)
        | (META if event.meta else 0)
        | (CTRL if event.ctrl else 0)
    )


def accepts_motion(pane: "Pane") -> bool:
    """Whether the application asked for reports while a button is held."""
    return pane.mouse_button or pane.mouse_all


def encode(
    pane: "Pane",
    button: int,
    x: int,
    y: int,
    *,
    release: bool = False,
    motion: bool = False,
    modifier_bits: int = 0,
) -> bytes | None:
    """Return a pane-local mouse report, or None if the app does not want it.

    ``x`` and ``y`` are one-based cell coordinates inside the pane.  SGR 1006
    is preferred; UTF-8 1005 and legacy X10 are kept for older applications.
    """
    if motion and not accepts_motion(pane):
        return None
    x = max(1, int(x))
    y = max(1, int(y))
    if pane.mouse_sgr:
        code = button | modifier_bits | (MOTION if motion else 0)
        return (
            f"\x1b[<{code};{x};{y}{'m' if release else 'M'}".encode("ascii")
        )
    code = button | modifier_bits
    if release:
        code = RELEASE | modifier_bits
    elif motion:
        code |= MOTION
    if pane.mouse_utf8:
        x = min(x, UTF8_MAX)
        y = min(y, UTF8_MAX)
        return (
            b"\x1b[M"
            + chr(32 + code).encode("utf-8")
            + chr(32 + x).encode("utf-8")
            + chr(32 + y).encode("utf-8")
        )
    x = min(x, LEGACY_MAX)
    y = min(y, LEGACY_MAX)
    return b"\x1b[M" + bytes((32 + code, 32 + x, 32 + y))
