"""Tmux layout gutters, rendered without covering or resizing pane contents."""

from functools import lru_cache


@lru_cache(maxsize=32)
def borders(width, height, layout):
    """Return rows of (glyph, active) cells from pane rectangles.

    Tmux reserves one cell between panes. Extend each internal edge through its
    end intersections, then derive junctions from neighbouring gutter cells.
    There is no outer frame, and a zoomed/single pane has no internal border.
    """
    cells = set()
    active = set()
    for x, y, w, h, focused in layout:
        edges = set()
        for column in (x - 1, x + w):
            if 0 <= column < width:
                edges.update(
                    (column, row)
                    for row in range(max(0, y - 1), min(height, y + h + 1))
                )
        for row in (y - 1, y + h):
            if 0 <= row < height:
                edges.update(
                    (column, row)
                    for column in range(max(0, x - 1), min(width, x + w + 1))
                )
        cells.update(edges)
        if focused:
            active.update(edges)
    # Rectangles are authoritative: never draw over any application cell.
    cells = {
        (x, y)
        for x, y in cells
        if not any(px <= x < px + w and py <= y < py + h for px, py, w, h, _ in layout)
    }
    # Match tmux redraw_mark_two_pane_colours: when two panes share an
    # entire divider, its first half belongs to left/top, the second to
    # right/bottom. Otherwise either focus would light the same whole line.
    if len(layout) == 2:
        first, second = sorted(layout, key=lambda p: (p[1], p[0]))
        if first[1] == second[1] and first[3] == second[3]:
            first, second = sorted(layout, key=lambda p: p[0])
            active = {
                (x, y) for x, y in cells if (first if y <= height // 2 else second)[4]
            }
        elif first[0] == second[0] and first[2] == second[2]:
            active = {
                (x, y) for x, y in cells if (first if x <= width // 2 else second)[4]
            }
    glyphs = {
        3: "│",
        12: "─",
        10: "┌",
        6: "┐",
        9: "└",
        5: "┘",
        11: "├",
        7: "┤",
        14: "┬",
        13: "┴",
        15: "┼",
    }
    rows = {}
    for x, y in cells:
        mask = sum(
            bit
            for dx, dy, bit in ((0, -1, 1), (0, 1, 2), (-1, 0, 4), (1, 0, 8))
            if (x + dx, y + dy) in cells
        )
        glyph = glyphs.get(mask, "│" if mask & 3 else "─")
        rows.setdefault(y, {})[x] = (glyph, (x, y) in active)
    return rows
