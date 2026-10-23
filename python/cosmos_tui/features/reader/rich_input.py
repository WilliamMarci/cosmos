"""Rich-document navigation and hit actions; no terminal output ownership."""

import asyncio
from cosmos_tui.features.reader.flow import position
from cosmos_tui.features.reader.inspector import copy_block


def seek(doc, pane, state, line):
    rows, _, _, height, count, _ = position(doc, pane, state)
    line = max(0, min(max(0, len(rows) - 1), line))
    state["section_line"] = line
    state["row"] = line
    state["page"] = line // (height * count) + 1
    state.pop("outline_scroll", None)


async def action(controller, pane, state, name, value=0):
    doc = controller.documents
    if name == "columns":
        _, _, _, _, _, old_start = await asyncio.to_thread(position, doc, pane, state)
        choices = ["auto", 1, 2, 3]
        current = state.get("columns", "auto")
        state["columns"] = choices[(choices.index(current) + 1) % len(choices)]
        seek(doc, pane, state, old_start)
    elif name == "mode":
        _, _, _, _, _, start = await asyncio.to_thread(position, doc, pane, state)
        state["reading_mode"] = (
            "pages" if state.get("reading_mode") == "scroll" else "scroll"
        )
        seek(doc, pane, state, start)
    elif name == "sidebar":
        state["thumbnails"] = not state.get("thumbnails", True)
    elif name == "outline":
        seek(doc, pane, state, value)
    elif name == "paragraph":
        state["selected_block"] = value
    elif name in ("expand", "table"):
        state.update(inspector=value, inspect_zoom=1, inspect_pan=[0, 0])
    elif name == "back":
        state.pop("inspector", None)
    elif name == "fold":
        values = set(state.get("collapsed_images", []))
        values.symmetric_difference_update({value})
        state["collapsed_images"] = sorted(values)
    elif name == "copy":
        try:
            await copy_block(doc, state, value)
        except (RuntimeError, OSError) as error:
            await controller.app.action_error("reader.copy", error)
        return
    await controller.update_viewer(pane, state)


async def key(controller, event, pane, state):
    char, key = event.character, event.key
    if state.get("inspector") is not None:
        if char == "?":
            return False
        if key in ("escape", "q"):
            state.pop("inspector", None)
        elif char == "y":
            await action(controller, pane, state, "copy", state["inspector"])
            return True
        elif char in ("+", "=", "-"):
            state["inspect_zoom"] = max(
                0.1,
                min(
                    8,
                    state.get("inspect_zoom", 1) * (1 / 1.25 if char == "-" else 1.25),
                ),
            )
        elif key == "space" or char == "0":
            state.update(inspect_zoom=1, inspect_pan=[0, 0])
        elif key in ("up", "down", "left", "right"):
            x, y = state.get("inspect_pan", [0, 0])
            source = next(
                r
                for r in controller.documents.rows(state["path"])
                if r.block == state["inspector"]
            )
            step = 1
            if source.image:
                image = await asyncio.to_thread(
                    controller.documents.asset, state["path"], *source.image
                )
                cw, ch = controller.cell_pixels()
                scale, (x, y) = controller.media.geometry(
                    image,
                    dict(zoom=state.get("inspect_zoom", 1), pan=[x, y]),
                    pane.width * cw,
                    max(1, pane.height - 1) * ch,
                )
                step = 4 * (cw if key in ("left", "right") else ch) / scale
            state["inspect_pan"] = [
                x + (step if key == "right" else -step if key == "left" else 0),
                y + (step if key == "down" else -step if key == "up" else 0),
            ]
        else:
            return True
        await controller.update_viewer(pane, state)
        return True
    if char in ("f", "y") and state.get("selected_block") is not None:
        await action(
            controller,
            pane,
            state,
            "fold" if char == "f" else "copy",
            state["selected_block"],
        )
        return True
    if char in ("c", "v", "o"):
        await action(
            controller, pane, state, {"c": "columns", "v": "mode", "o": "sidebar"}[char]
        )
        return True
    rows, _, _, height, count, start = await asyncio.to_thread(
        position, controller.documents, pane, state
    )
    stride = height * count
    if key in ("tab", "shift+tab"):
        blocks = [
            (i, r.block)
            for i, r in enumerate(rows)
            if r.block >= 0 and (i == 0 or rows[i - 1].block != r.block)
        ]
        current = state.get("selected_block")
        index = next(
            (n for n, (_, block) in enumerate(blocks) if block == current), None
        )
        if index is None:
            index = next(
                (n for n, (i, _) in enumerate(blocks) if i >= start), len(blocks) - 1
            )
            if key == "shift+tab":
                index -= 1
        else:
            index += -1 if key == "shift+tab" else 1
        if blocks:
            line, block = blocks[max(0, min(len(blocks) - 1, index))]
            state["selected_block"] = block
            state["section_line"] = line
            if not start <= line < start + stride:
                seek(controller.documents, pane, state, line)
    elif key == "enter" and state.get("selected_block") is not None:
        block = state["selected_block"]
        source = next(
            (r for r in controller.documents.rows(state["path"]) if r.block == block),
            None,
        )
        if source and (source.image or source.table):
            await action(controller, pane, state, "expand", block)
            return True
    elif key in (
        "up",
        "down",
        "left",
        "right",
        "pageup",
        "pagedown",
        "home",
        "end",
    ) or char in ("[", "]", ",", "."):
        if char in ("[", ","):
            key = "left"
        elif char in ("]", "."):
            key = "right"
        step = (
            1
            if state.get("reading_mode") == "scroll" and key in ("up", "down")
            else stride
        )
        delta = -step if key in ("up", "left", "pageup") else step
        target = (
            0 if key == "home" else len(rows) - 1 if key == "end" else start + delta
        )
        seek(controller.documents, pane, state, target)
    else:
        return False
    await controller.update_viewer(pane, state)
    return True
