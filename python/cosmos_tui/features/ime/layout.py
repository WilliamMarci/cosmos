"""Host-independent two-row IME layout with a real composition caret."""

from cosmos_tui.ui.cells import CellRun, HitRegion, Rect, UIFrame, cell_width, clip

STYLES = {
    "normal": "0123456789",
    "superscript": "⁰¹²³⁴⁵⁶⁷⁸⁹",
    "subscript": "₀₁₂₃₄₅₆₇₈₉",
}


def compose(context, area, cursor, palette, style="normal"):
    preedit = context["preedit"]
    caret = max(0, min(len(preedit), context.get("cursor", len(preedit))))
    labels = [f" {i + 1} {text} " for i, text in enumerate(context["candidates"])]
    width = min(
        area.width, max(12, cell_width(preedit) + 1, sum(map(cell_width, labels)) + 4)
    )
    height = min(2, area.height)
    x = max(area.x, min(cursor[0], area.x + area.width - width))
    bottom = area.y + area.height
    y = (
        cursor[1] + 1
        if cursor[1] + 1 + height <= bottom
        else max(area.y, cursor[1] - height)
    )
    runs = [CellRun(Rect(x, y, width), " " * width, palette["fg"], palette["base"])]
    # Keep the editable caret visible even when preedit is wider than the pane.
    start = 0
    while cell_width(preedit[start:caret]) >= width and start < caret:
        start += 1
    offset = 0
    selection = context.get("selection", (0, 0))
    for index in range(start, len(preedit) + 1):
        if index == caret and offset < width:
            runs.append(
                CellRun(
                    Rect(x + offset, y, 1),
                    "▏",
                    palette["accl"],
                    palette["base"],
                    reverse=True,
                )
            )
            offset += 1
        if index == len(preedit) or offset >= width:
            break
        character = preedit[index]
        size = cell_width(character)
        if offset + size > width:
            break
        runs.append(
            CellRun(
                Rect(x + offset, y, size),
                character,
                palette["accl"],
                palette["base"],
                bold=selection[0] <= index < selection[1],
                underline=not character.isspace(),
            )
        )
        offset += size
    hits = []
    if height == 2:
        runs.append(
            CellRun(Rect(x, y + 1, width), " " * width, palette["fg"], palette["base"])
        )
        limit = max(0, width - 4)
        offset = 0
        digits = STYLES.get(style, STYLES["normal"])
        for i, candidate in enumerate(context["candidates"]):
            prefix = (
                " " + str(i + 1).translate(str.maketrans("0123456789", digits)) + " "
            )
            label = clip(prefix + candidate + " ", limit - offset)
            size = cell_width(label)
            if size <= cell_width(prefix):
                break
            selected = i == context["selected"]
            background = palette["acc"] if selected else palette["base"]
            rect = Rect(x + offset, y + 1, size)
            runs.append(
                CellRun(
                    rect,
                    label,
                    palette["on"] if selected else palette["fg"],
                    background,
                    selected,
                )
            )
            runs.append(
                CellRun(
                    Rect(x + offset, y + 1, cell_width(prefix)),
                    prefix,
                    "yellow",
                    background,
                    True,
                )
            )
            hits.append(HitRegion(str(i + 1), rect))
            offset += size
        for dx, action, enabled, solid, outline in [
            (width - 3, "pageup", context.get("page", 0) > 0, "◂", "◃"),
            (width - 1, "pagedown", not context.get("last_page", False), "▸", "▹"),
        ]:
            if dx >= 0:
                rect = Rect(x + dx, y + 1, 1)
                runs.append(
                    CellRun(
                        rect,
                        solid if enabled else outline,
                        palette["accl"] if enabled else palette["mute"],
                        palette["base"],
                    )
                )
                hits.append(HitRegion(action, rect, enabled))
    return UIFrame(Rect(x, y, width, height), tuple(runs), tuple(hits))
