"""Image-footprint-only pending/error surfaces within reflowed documents."""

import time
from PIL import ImageDraw
from rich.text import Text

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def placeholder(
    canvas, lines, x, y, width, height, source, max_rows, palette, cell, put, error=None
):
    cw, ch = cell
    sw, sh = source
    scale = min(1, width * cw / sw, max_rows * ch / sh)
    w, h = max(1, round(sw * scale)), max(1, round(sh * scale))
    left, top = x * cw, max(0, y * ch)
    bottom = min(height * ch, y * ch + h)
    if bottom <= top:
        return
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (left, top, left + w - 1, bottom - 1),
        fill=palette["base"],
        outline=palette["mute"],
    )
    end = min(height - 1, max(0, (bottom - 1) // ch))
    for row in range(max(0, y), end + 1):
        put(
            lines,
            x,
            row,
            Text(" " * min(width, (w + cw - 1) // cw), style=f"on {palette['base']}"),
            width,
        )
    # Only draw a text-sized spinner when a full terminal cell fits inside
    # the image rectangle. Tiny icons must not leak labels into nearby text.
    end = min(height - 1, bottom // ch - 1)
    if w < cw * 2 or end < max(0, y):
        return
    label = Text(
        str(error) if error else SPINNER[int(time.monotonic() * 4) % len(SPINNER)],
        style=palette["mute"],
    )
    label.truncate(max(1, min(width, w // cw)))
    put(
        lines,
        x + max(0, min(width, w // cw) - label.cell_len),
        end,
        label,
        label.cell_len,
    )
