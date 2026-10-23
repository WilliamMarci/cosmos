"""Independent rectangular reader actions without decorative separators."""

from cosmos_tui.ui.blocks import color_block


def buttons(image=False, folded=False, expanded=False):
    if expanded:
        return [("back", "←"), ("copy", "⎘")]
    if image:
        return [
            ("fold", "▸" if folded else "▾"),
            ("expand", "↗"),
            ("copy", "⎘"),
        ]
    return [("table", "Table"), ("copy", "⎘")]


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
    canvas=None,
    cell=(10, 20),
):
    hits, offset = [], 0
    for index, (action, label) in enumerate(items):
        hovered = hover == [action, block]
        background = palette["acc"] if hovered else palette["base"]
        foreground = palette["on"] if hovered else palette["fg"]
        text = color_block(label, foreground, background)
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
