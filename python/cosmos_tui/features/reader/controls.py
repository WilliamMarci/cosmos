"""Compact borderless asset controls, shared by inline and expanded views."""

from rich.text import Text


def buttons(image=False, folded=False, expanded=False):
    if expanded:
        return [("back", "Back"), ("copy", "🗎")]
    if image:
        return [
            ("fold", "▸ Show" if folded else "▾ Fold"),
            ("expand", "🖼 Expand"),
            ("copy", "🗎"),
        ]
    return [("table", "Open table"), ("copy", "🗎")]


def draw_buttons(lines, x, y, width, items, block, hover, palette, put):
    hits = []
    offset = 0
    for action, label in items:
        text = Text(
            " " + label + " ",
            style=f"{palette['fg']} on {palette['acc'] if hover == [action, block] else palette['base']}",
        )
        length = min(text.cell_len, max(0, width - offset))
        if not length:
            break
        put(lines, x + offset, y, text, length)
        if 0 <= y < len(lines):
            hits.append((x + offset, y, length, 1, (action, block)))
        offset += text.cell_len + 1
    return hits
