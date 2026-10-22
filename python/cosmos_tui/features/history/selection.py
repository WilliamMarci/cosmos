"""Search prompt for native Tmux copy mode; history stays in Tmux."""


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
