"""Reflow and viewport composition for rich documents, independent of Textual."""

from pathlib import Path
import re
import zipfile

from PIL import Image
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from cosmos_tui.features.reader.layout import ReadingFrame

IMAGE_ROWS = 8
ICON_EDGE = 64
_CONSOLE = Console(color_system="truecolor")


def geometry(pane, state):
    sidebar = (
        min(26, pane.width // 3)
        if state.get("thumbnails", True) and pane.width >= 45 and pane.height >= 12
        else 0
    )
    available = max(1, pane.width - sidebar - 2)
    requested = state.get("columns", "auto")
    count = (
        min(3, max(1, (available + 3) // 65))
        if requested == "auto"
        else max(1, min(3, int(requested)))
    )
    count = min(count, max(1, available // 24))
    width = max(1, (available - (count - 1) * 3) // count)
    return sidebar, width, max(1, pane.height - 1), count


def reflow(doc, path, width, state, cell):
    from cosmos_tui.features.reader.documents import Row

    rows = []
    collapsed = state.get("collapsed_images", [])
    for source in doc.rows(path):
        if source.image:
            height = IMAGE_ROWS
            icon = False
            if source.block in collapsed:
                height = 0
            else:
                try:
                    image_width, image_height = doc.asset_size(path, *source.image)
                    icon = max(image_width, image_height) <= ICON_EDGE
                    scale = min(
                        1,
                        width * cell[0] / image_width,
                        IMAGE_ROWS * cell[1] / image_height,
                    )
                    height = max(
                        1, int((image_height * scale + cell[1] - 1) // cell[1])
                    )
                except (
                    OSError,
                    ValueError,
                    zipfile.BadZipFile,
                    Image.DecompressionBombError,
                ):
                    pass
            if not icon:
                rows.append(Row(Text(""), block=source.block, table=True))
            if source.block not in collapsed:
                rows.append(Row(Text("[Image]"), source.image, block=source.block))
                rows.extend(
                    Row(Text(""), block=source.block) for _ in range(max(0, height - 1))
                )
        elif source.table:
            parts = source.text.split("\n")
            if max((t.cell_len for t in parts), default=0) > width:
                rows.append(Row(Text("[Open table]"), block=source.block, table=True))
            else:
                rows.extend(Row(t, block=source.block) for t in parts)
                rows.append(
                    Row(Text("[Open table] [copy]"), block=source.block, table=True)
                )
        else:
            rows.extend(
                Row(t, heading=source.heading and i == 0, block=source.block)
                for i, t in enumerate(
                    source.text.wrap(doc.console, width, overflow="fold")
                )
            )
        if len(rows) > 200000:
            raise ValueError("Reflowed document exceeds 200000 rows")
    return rows


def position(doc, pane, state):
    sidebar, width, height, count = geometry(pane, state)
    rows = doc.layout(state["path"], width, state, tuple(state.get("_cell", (10, 20))))
    stride = height * count
    if state.get("reading_mode", "pages") == "scroll":
        start = max(
            0,
            min(
                max(0, len(rows) - stride),
                int(state.get("row", (state.get("page", 1) - 1) * stride)),
            ),
        )
    else:
        page = min(
            max(1, (len(rows) + stride - 1) // stride),
            max(1, int(state.get("page", 1))),
        )
        start = (page - 1) * stride
    return rows, sidebar, width, height, count, start


def put(lines, x, y, text, width):
    if not 0 <= y < len(lines):
        return
    from textual.strip import Strip

    console = _CONSOLE

    def crop(value, begin, end):
        return Text.assemble(
            *[
                (s.text, s.style)
                for s in Strip(list(value.render(console))).crop(begin, end)
            ]
        )

    text = crop(text, 0, max(0, width))
    lines[y] = (
        crop(lines[y], 0, x)
        + text
        + crop(lines[y], x + text.cell_len, lines[y].cell_len)
    )


def render(doc, pane, state, palette, cell):
    state = dict(state, _cell=cell)
    rows, sidebar, width, height, count, start = position(doc, pane, state)
    stride = height * count
    pages = max(1, (len(rows) + stride - 1) // stride)
    page = start // stride + 1
    cw, ch = cell
    canvas = Image.new("RGB", (pane.width * cw, pane.height * ch), palette["bg"])
    style = f"{palette['fg']} on {palette['bg']}"
    lines = [Text(" " * pane.width, style=style) for _ in range(pane.height)]
    hits = []
    selected = state.get("selected_block", -2)
    sources = {r.block: r for r in doc.rows(state["path"]) if r.block >= 0}
    for column in range(count):
        x = sidebar + 1 + column * (width + 3)
        begin = start + column * height
        for index in range(max(0, begin - IMAGE_ROWS), min(len(rows), begin + height)):
            row = rows[index]
            y = index - begin
            if y < 0 and not row.image:
                continue
            text = row.text.copy()
            if state.get("query"):
                text.highlight_regex(
                    re.escape(state["query"]),
                    f"black on {palette['accl']}",
                    re_flags=re.IGNORECASE,
                )
            if row.block == selected:
                text.stylize(f"on {palette['base']}")
            if y >= 0:
                put(lines, x, y, text, width)
                hits.append((x, y, width, 1, ("paragraph", row.block)))
            if row.table:
                source = sources.get(row.block)
                from cosmos_tui.features.reader.controls import buttons, draw_buttons

                hits.extend(
                    draw_buttons(
                        lines,
                        x,
                        y,
                        width,
                        buttons(
                            image=bool(source and source.image),
                            folded=row.block in state.get("collapsed_images", []),
                        ),
                        row.block,
                        state.get("hover"),
                        palette,
                        put,
                    )
                )
            if row.image and row.block not in state.get("collapsed_images", []):
                try:
                    image = doc.asset(state["path"], *row.image)
                    icon = max(image.size) <= ICON_EDGE
                    image.thumbnail(
                        (width * cw, IMAGE_ROWS * ch), Image.Resampling.LANCZOS
                    )
                    # Crop to this column: an image may straddle a logical page.
                    top = max(0, -y * ch)
                    bottom = min(image.height, (height - y) * ch)
                    if bottom > top:
                        canvas.paste(
                            image.crop((0, top, image.width, bottom)),
                            (x * cw, max(0, y * ch)),
                        )
                    if y >= 0:
                        put(lines, x, y, Text(" " * width, style=style), width)
                    visible_y = max(0, y)
                    visible_h = min(
                        height - visible_y, max(1, (bottom - top + ch - 1) // ch)
                    )
                    if not icon:
                        hits.append(
                            (x, visible_y, width, visible_h, ("expand", row.block))
                        )
                except (
                    OSError,
                    ValueError,
                    Image.DecompressionBombError,
                    zipfile.BadZipFile,
                ) as error:
                    put(
                        lines,
                        x,
                        y,
                        Text(f"[Image: {error}]", style=palette["mute"]),
                        width,
                    )
    headings = [(i, r) for i, r in enumerate(rows) if r.heading]
    anchor = state.get("section_line", start)
    if not start <= anchor < start + stride:
        anchor = start
    active = max((n for n, (i, _) in enumerate(headings) if i <= anchor), default=0)
    if sidebar:
        put(
            lines,
            0,
            0,
            Text(
                " Outline [fold]".ljust(sidebar),
                style=f"{palette['accl']} on {palette['base']}",
            ),
            sidebar,
        )
        hits.append((0, 0, sidebar, 1, ("sidebar", 0)))
        offset = max(
            0, min(max(0, len(headings) - height + 1), active - (height - 2) // 2)
        )
        offset = int(state.get("outline_scroll", offset))
        for y, (line, row) in enumerate(headings[offset : offset + height - 1], 1):
            highlighted = offset + y - 1 == active or state.get("hover") == [
                "outline",
                line,
            ]
            text = Text(
                " " + row.text.plain,
                style=f"{palette['accl'] if highlighted else palette['fg']} on {palette['base']}",
            )
            text.truncate(sidebar)
            text.pad_right(max(0, sidebar - text.cell_len))
            put(lines, 0, y, text, sidebar)
            hits.append((0, y, sidebar, 1, ("outline", line)))
    if state.get("inspector") is not None:
        from cosmos_tui.features.reader.inspector import render_inspector

        canvas, lines, hits = render_inspector(doc, pane, state, palette, cell)
    else:
        footer = Text(
            f" {Path(state['path']).name} ",
            style=f"{palette['fg']} on {palette['base']}",
        )
        suffix = f" [columns:{state.get('columns', 'auto')}] [mode:{state.get('reading_mode', 'pages')}] {page}/{pages} "
        footer.truncate(max(0, pane.width - cell_len(suffix)))
        footer.pad_right(max(0, pane.width - cell_len(suffix) - footer.cell_len))
        begin = footer.cell_len
        footer.append(suffix)
        footer.truncate(pane.width)
        lines[-1] = footer
        hits.extend(
            [
                (
                    begin,
                    height,
                    len(f" [columns:{state.get('columns', 'auto')}]"),
                    1,
                    ("columns", 0),
                ),
                (
                    begin + len(f" [columns:{state.get('columns', 'auto')}]"),
                    height,
                    len(f" [mode:{state.get('reading_mode', 'pages')}]"),
                    1,
                    ("mode", 0),
                ),
            ]
        )
    return ReadingFrame(
        canvas,
        lines,
        range(1, pages + 1),
        page - 1,
        hits,
        height,
        sidebar,
        pane.width - sidebar,
        1,
        canvas.size,
        (0, 0),
    ), pages
