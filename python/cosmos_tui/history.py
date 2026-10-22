"""Search prompt for native Tmux copy mode; history stays in Tmux."""

from textual.binding import Binding
from .chrome import Frame
from .shortcuts import CosmosInput, CosmosModal
from .surfaces import Zone


def selection_range(pane, row):
    """Visible selection range in terminal cells, with native mode end semantics."""
    if not pane.selection:
        return None
    sx, sy, ex, ey = pane.selection
    (sy, sx), (ey, ex) = sorted(((sy, sx), (ey, ex)))
    if not sy <= row <= ey:
        return None
    if pane.selection_rectangle:
        left, right = sorted((sx, ex))
    else:
        left = sx if row == sy else 0
        right = ex if row == ey else pane.width
    right += int(pane.selection_inclusive)
    left, right = max(0, left), min(pane.width, right)
    return (left, right) if left < right else None


class HistorySearch(CosmosModal):
    zone = Zone.POP_WINDOW
    DEFAULT_CSS = "HistorySearch { align: center middle; background: transparent; } #history-search-frame { width: 60; max-width: 90%; height: auto; }"
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, backward=False):
        super().__init__()
        self.backward = backward

    def compose(self):
        with Frame(id="history-search-frame") as frame:
            frame.set_heading(
                "Search history backward" if self.backward else "Search history",
                "copy.search_backward" if self.backward else "copy.search",
            )
            yield CosmosInput(
                placeholder="Search retained pane output", id="history-query"
            )

    def on_mount(self):
        self.query_one(CosmosInput).focus()

    def on_input_submitted(self, event):
        self.dismiss(event.value or None)

    def action_cancel(self):
        self.dismiss(None)
