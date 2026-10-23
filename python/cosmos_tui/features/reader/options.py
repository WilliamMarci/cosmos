"""Pane-clipped reader footer and compact upward choice menu."""

from pathlib import Path
from PIL import ImageDraw
from rich.text import Text
from cosmos_tui.features.reader.controls import draw_buttons

OPTIONS = (
    ("columns", "Col", ("auto", 1, 2, 3)),
    ("reading_mode", "Scroll", ("pages", "scroll")),
    ("line_space", "Ln space", (0, 1, 2, 3)),
    ("inline_rows", "Image size", (4, 6, 8, 12, 16, 18, 24, 32)),
)


def choices(state, index):
    key, label, values = OPTIONS[index]
    value = state.get(key, state.get("image_rows", 8) if key == "inline_rows" else 1)
    if key == "columns" and value != "auto":
        value = int(value)
    return key, label, values, value


def value_label(key, value):
    if key == "reading_mode":
        return "Enable" if value == "scroll" else "Disable"
    if key == "inline_rows":
        return f"{value} ln"
    return str(value).capitalize()


def draw_footer(canvas, lines, pane, state, palette, cell, page, pages, chapter, put):
    y = pane.height - 1
    if y < 0:
        return []
    lines[y] = Text(" " * pane.width, style=f"{palette['fg']} on {palette['base']}")
    progress = f" {round(page / max(1, pages) * 100):d}% {page}/{pages} "
    outline_width, options_width = min(3, pane.width), min(3, max(0, pane.width - 3))
    outline_x = max(0, pane.width - outline_width)
    progress_width = min(len(progress), max(0, outline_x - options_width))
    progress_x = outline_x - progress_width
    options_x = max(0, progress_x - options_width)
    title = Text(" " + Path(state["path"]).name, style=palette["fg"])
    title.truncate(
        max(0, options_x // 2 if chapter else options_x), overflow="ellipsis"
    )
    if chapter:
        title.append(" · " + chapter, style=palette["mute"])
    put(lines, 0, y, title, options_x)
    put(
        lines,
        progress_x,
        y,
        Text(
            progress[-progress_width:] if progress_width else "", style=palette["mute"]
        ),
        progress_width,
    )
    hits = draw_buttons(
        lines,
        options_x,
        y,
        options_width,
        [("options", "≡")],
        0,
        ["options", 0] if state.get("_options_open") else state.get("hover"),
        palette,
        put,
        canvas=canvas,
        cell=cell,
    )
    hits.extend(
        draw_buttons(
            lines,
            outline_x,
            y,
            outline_width,
            [("sidebar", "▤")],
            0,
            ["sidebar", 0] if state.get("thumbnails", True) else state.get("hover"),
            palette,
            put,
            canvas=canvas,
            cell=cell,
        )
    )
    return hits


def draw_menu(canvas, lines, pane, state, palette, cell, put):
    if not state.get("_options_open") or pane.height < 2:
        return []
    width = min(27, pane.width)
    height = min(len(OPTIONS), pane.height - 1)
    selected = max(0, min(len(OPTIONS) - 1, state.get("_option_index", 0)))
    offset = max(0, selected - height + 1)
    top = pane.height - 1 - height
    # Place above the footer's Options control; clamp within the reader pane.
    footer_hit = next(
        (h for h in state.get("_footer_hits", []) if h[-1][0] == "options"), None
    )
    x = max(0, min(pane.width - width, footer_hit[0] if footer_hit else 0))
    hits = []
    draw = ImageDraw.Draw(canvas)
    cw, ch = cell
    for index in range(offset, offset + height):
        key, label, _, value = choices(state, index)
        y = top + index - offset
        hover = state.get("hover") or []
        active = index == selected or (
            len(hover) == 2
            and hover[0] in ("option_previous", "option_next")
            and hover[1] == index
        )
        background = palette["base"] if not active else palette["acc"]
        foreground = palette["fg"] if not active else palette["on"]
        draw.rectangle(
            (x * cw, y * ch, (x + width) * cw - 1, (y + 1) * ch - 1), fill=background
        )
        text = Text(" " + label, style=f"{foreground} on {background}")
        suffix = " ◂ " + value_label(key, value) + " ▸ "
        text.truncate(max(0, width - len(suffix)))
        text.pad_right(max(0, width - len(suffix) - text.cell_len))
        text.append(suffix)
        put(lines, x, y, text, width)
        hits.append((x, y, width, 1, ("option_next", index)))
        left = max(x, x + width - len(suffix) + 1)
        right = max(x, x + width - 2)
        hits.extend(
            [
                (left, y, 1, 1, ("option_previous", index)),
                (right, y, 1, 1, ("option_next", index)),
            ]
        )
    return hits
