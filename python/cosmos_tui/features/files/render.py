"""Yazi-like parent/current/preview columns, drawn once by Cosmos."""

from pathlib import Path
from PIL import Image, ImageDraw
from rich.text import Text
from cosmos_tui.features.files.model import display, preview
from cosmos_tui.features.files.style import appearance
from cosmos_tui.features.reader.flow import put
from cosmos_tui.features.reader.layout import ReadingFrame


def render(manager, pane, state, palette, cell):
    items = manager.listing(state)
    width, height = pane.width, pane.height
    cw, ch = cell
    canvas = Image.new("RGB", (width * cw, height * ch), palette["bg"])
    lines = [
        Text(" " * width, style=f"{palette['fg']} on {palette['bg']}")
        for _ in range(height)
    ]
    settings = manager.controller.app.settings
    borders = settings.get("files_border", "dividers")
    inset = 1 if borders == "frame" and width >= 8 and height >= 5 else 0
    start_y, rows = 1 + inset, max(1, height - 1 - 2 * inset)
    cursor = max(0, min(len(items) - 1, state.get("cursor", 0)))
    selected = set(state.get("selected", []))
    left = max(14, width // 6) if width >= 90 else 0
    middle_end = width * 3 // 5 if width >= 55 else width - inset
    current_x = left + 1 if left else inset
    current_width = max(1, middle_end - current_x)
    hits = []

    def line(x, y, text, limit):
        put(lines, x, y, text, max(0, limit))

    def column(values, x, size, active=None, clicks=False):
        top = max(0, min((active or 0) - rows // 2, max(0, len(values) - rows)))
        for y, i in enumerate(range(top, min(len(values), top + rows)), start_y):
            item = values[i]
            focus = active is not None and i == active
            fg, icon = appearance(item, palette)
            bg = palette["acc"] if focus else palette["bg"]
            if focus:
                fg = palette["on"]
                ImageDraw.Draw(canvas).rectangle(
                    (x * cw, y * ch, (x + size) * cw - 1, (y + 1) * ch - 1), fill=bg
                )
            label = Text(" " * size, style=f"{fg} on {bg}")
            marker = "●" if item["path"] in selected else " "
            prefix = marker + (icon + " " if settings.get("files_icons", False) else "")
            name = display(item["name"]) + ("/" if item["directory"] else "")
            if item["link"]:
                name += " → " + display(item.get("target", ""))
            value = Text(prefix + name, style=f"{fg} on {bg}")
            value.truncate(max(1, size), overflow="ellipsis")
            label = value + label[value.cell_len :]
            line(x, y, label, size)
            if clicks:
                hits.append((x, y, size, 1, ("file_entry", i)))

    path = Text(" " + display(state["path"]), style=palette["accl"])
    path.truncate(max(1, width - 2 * inset), overflow="ellipsis")
    line(inset, inset, path, width - 2 * inset)
    if left:
        try:
            parent_items = manager.listing(
                dict(
                    state, path=str(Path(state["path"]).parent), filter="", selected=[]
                )
            )
            active = next(
                (
                    i
                    for i, item in enumerate(parent_items)
                    if Path(item["path"]) == Path(state["path"])
                ),
                None,
            )
            column(parent_items, inset, left - inset, active)
        except (OSError, ValueError):
            pass
    column(items, current_x, current_width, cursor, True)
    if not items:
        line(
            current_x + 1,
            start_y,
            Text("No matching files", style=palette["mute"]),
            current_width - 1,
        )
    if middle_end < width - inset and items:
        item = items[cursor]
        x, size = middle_end + 2, width - middle_end - 3 - inset
        try:
            if item["directory"]:
                children = manager.listing(
                    dict(state, path=item["path"], filter="", cursor=0, selected=[])
                )
                column(children, x, max(1, size))
            else:
                for y, text in enumerate(preview(item).splitlines()[:rows], start_y):
                    line(
                        x,
                        y,
                        Text(display(text.expandtabs(4)), style=palette["mute"]),
                        size,
                    )
        except OSError as error:
            line(
                x,
                start_y,
                Text(display(str(error)), style=palette.get("error", palette["mute"])),
                size,
            )
    if borders != "none":
        for x in ([left] if left else []) + (
            [middle_end] if middle_end < width - inset else []
        ):
            for y in range(start_y, height - inset):
                line(x, y, Text("│", style=palette["mute"]), 1)
    if inset:
        edge = palette["mute"]
        line(0, 0, Text("╭" + "─" * (width - 2) + "╮", style=edge), width)
        line(0, height - 1, Text("╰" + "─" * (width - 2) + "╯", style=edge), width)
        for y in range(1, height - 1):
            line(0, y, Text("│", style=edge), 1)
            line(width - 1, y, Text("│", style=edge), 1)
        for x in ([left] if left else []) + (
            [middle_end] if middle_end < width - 1 else []
        ):
            line(x, height - 1, Text("┴", style=edge), 1)
    return ReadingFrame(
        canvas,
        lines,
        items,
        cursor,
        hits,
        rows,
        current_x,
        current_width,
        1,
        canvas.size,
        (0, 0),
    )
