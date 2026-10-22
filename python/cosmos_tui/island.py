"""Pure island geometry: safe source anchor, cell widths and narrow fallback."""

from dataclasses import dataclass
from .ui import Rect


@dataclass
class IslandViewState:
    measured_width: int = 0
    actions_visible: bool = False
    action_focus: str | None = None
    completion_timestamp: float = 0
    generation_started_at: float = 0


@dataclass(frozen=True)
class IslandLayout:
    bounds: Rect
    input_surface: Rect
    editor: Rect
    status: Rect | None
    actions: tuple[tuple[str, Rect], ...]
    error: Rect | None
    can_expand: bool


def layout_island(
    pane, command: Rect, request, expanded=False, error=False, held_width=0
):
    px, py, pw, ph = pane.x, pane.y, pane.width, pane.height
    if (
        command.x != px
        or command.width != pw
        or command.y < py
        or command.y + command.height > py + ph
    ):
        return None
    # User-reviewed revision: use the entire source pane, without outer
    # width cap or gap before buttons; one leading cell precedes the dot.
    maximum = pw
    if maximum <= 0:
        return None
    width = maximum
    can_expand = width - 12 >= 12
    show = expanded and can_expand
    heights = (2, 1) if error else (1,)
    for height in heights:
        below, above = command.y + command.height, command.y - height
        y = below if below + height <= py + ph else above if above >= py else None
        if y is not None:
            break
    if y is None:
        return None
    x = px
    surface_width = width - 9 if show else width
    minimal = maximum < 6
    status = None if minimal else Rect(x + 1, y, 1)
    editor = Rect(x if minimal else x + 3, y, width if minimal else surface_width - 3)
    actions = (
        tuple(
            (name, Rect(x + surface_width + i * 3, y, 3))
            for i, name in enumerate(("agent", "cancel", "run"))
        )
        if show
        else ()
    )
    return IslandLayout(
        Rect(x, y, width, height),
        Rect(x, y, surface_width),
        editor,
        status,
        actions,
        Rect(x, y + 1, surface_width) if height == 2 else None,
        can_expand,
    )
