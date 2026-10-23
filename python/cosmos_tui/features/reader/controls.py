"""Solid-color reader controls sharing status-bar block and separator primitives."""

from cosmos_tui.ui.blocks import color_block, transition


def buttons(image=False, folded=False, expanded=False):
    if expanded:
        return [("back", "Back"), ("copy", "Copy")]
    if image:
        return [
            ("fold", "▸ Show" if folded else "▾ Fold"),
            ("expand", "Expand"),
            ("copy", "Copy"),
        ]
    return [("table", "Table"), ("copy", "Copy")]


def draw_buttons(
    lines,
    x,
    y,
    width,
    items,
    block,
    hover,
    palette,
    put,
    separator="powerline",
    canvas=None,
    cell=(10, 20),
):
    hits, offset = [], 0
    for index, (action, label) in enumerate(items):
        hovered = hover == [action, block]
        # Flat monochrome text; alternating solid blocks use the same theme roles
        # and neighboring-background joins as the global status bar.
        background = (
            palette["acc"]
            if hovered
            else palette["base"]
            if index % 2 == 0
            else palette["mute"]
        )
        foreground = "black" if index % 2 and not hovered else palette["fg"]
        text = color_block(label, foreground, background)
        after = palette["bg"]
        if index + 1 < len(items):
            next_action = items[index + 1][0]
            after = (
                palette["acc"]
                if hover == [next_action, block]
                else palette["base"]
                if (index + 1) % 2 == 0
                else palette["mute"]
            )
        text += transition(separator, background, after)
        length = min(text.cell_len, max(0, width - offset))
        if not length:
            break
        put(lines, x + offset, y, text, length)
        if canvas is not None and 0 <= y < len(lines):
            from PIL import ImageDraw
            from rich.console import Console

            draw = ImageDraw.Draw(canvas)
            cursor = 0
            for segment in text.render(Console(color_system="truecolor")):
                if segment.style and segment.style.bgcolor:
                    end = min(length, cursor + segment.cell_length)
                    if cursor < end:
                        color = segment.style.bgcolor.get_truecolor()
                        draw.rectangle(
                            (
                                (x + offset + cursor) * cell[0],
                                y * cell[1],
                                (x + offset + end) * cell[0] - 1,
                                (y + 1) * cell[1] - 1,
                            ),
                            fill=tuple(color),
                        )
                cursor += segment.cell_length
        if 0 <= y < len(lines):
            hits.append((x + offset, y, length, 1, (action, block)))
        offset += text.cell_len
    return hits
