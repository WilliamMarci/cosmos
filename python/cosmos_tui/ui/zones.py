"""Presentation slots shared by built-ins and future Mod presenters."""

from enum import StrEnum


class Zone(StrEnum):
    SESSION_WINDOW = "session_window"
    POP_WINDOW = "pop_window"
    LEFT_PANEL = "left_panel"
    BOTTOM_STATUS = "bottom_status_bar"
    BOTTOM_POWERLINE = "bottom_powerline"
    INSERT_COVER = "insert_cover_line"
    NOTIFICATION = "notification"


def cover_rect(pane, rows=1):
    """Clip a cursor-anchored cover inside its source pane, never resize its PTY."""
    rows = min(max(1, rows), pane.height)
    return (
        pane.x,
        max(pane.y, min(pane.y + pane.cursor[1], pane.y + pane.height - rows)),
        pane.width,
        rows,
    )
