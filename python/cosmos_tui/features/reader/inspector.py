"""Pane-local image/table inspector and optional host clipboard adapter."""

import asyncio
import io
import os
import shutil

from PIL import Image, ImageDraw
from rich.text import Text


def source(doc, state, block):
    return next(r for r in doc.rows(state["path"]) if r.block == block)


def render_inspector(doc, pane, state, palette, cell):
    row = source(doc, state, state["inspector"])
    cw, ch = cell
    height = max(1, pane.height - 1)
    canvas = Image.new("RGB", (pane.width * cw, pane.height * ch), palette["bg"])
    lines = [
        Text(" " * pane.width, style=f"{palette['fg']} on {palette['bg']}")
        for _ in range(pane.height)
    ]
    dx, dy = state.get("inspect_pan", [0, 0])
    if row.image:
        image = doc.asset(state["path"], *row.image)
        # Reuse the normal image Reader: same viewport, zoom, clamping and cache.
        image_state = dict(
            path=state["path"],
            page=1,
            thumbnails=False,
            zoom=state.get("inspect_zoom", 1),
            pan=state.get("inspect_pan", [0, 0]),
        )
        frame = doc.image_reader.render(
            image, image_state, 1, pane.width, pane.height, cell, palette, True
        )
        canvas, lines = frame.image.copy(), [line.copy() for line in frame.lines]
        # The document inspector has no image-directory thumbnail toggle.
        from cosmos_tui.features.reader.flow import put

        put(
            lines,
            max(0, pane.width - 3),
            height,
            Text(" " * min(3, pane.width), style=f"on {palette['base']}"),
            3,
        )
    else:
        for y, text in enumerate(
            row.text.split("\n")[max(0, dy) : max(0, dy) + height]
        ):
            # Clip by cells rather than codepoints so CJK table columns stay aligned.
            from textual.strip import Strip

            cut = Strip(list(text.render(doc.console))).crop(
                max(0, dx), max(0, dx) + pane.width
            )
            lines[y] = Text.assemble(*[(s.text, s.style) for s in cut])
    from cosmos_tui.features.reader.controls import buttons, draw_buttons
    from cosmos_tui.features.reader.flow import put

    if not row.image:
        lines[-1] = Text(
            " " * pane.width, style=f"{palette['fg']} on {palette['base']}"
        )
    ImageDraw.Draw(canvas).rectangle(
        (
            max(0, pane.width - 3) * cw,
            height * ch,
            pane.width * cw - 1,
            pane.height * ch - 1,
        ),
        fill=palette["base"],
    )
    if not row.image:
        ImageDraw.Draw(canvas).rectangle(
            (0, height * ch, pane.width * cw - 1, pane.height * ch - 1),
            fill=palette["base"],
        )
    hits = draw_buttons(
        lines,
        0,
        height,
        pane.width,
        buttons(expanded=True),
        row.block,
        state.get("hover"),
        palette,
        put,
        canvas,
        cell,
    )
    return canvas, lines, hits


async def copy_block(doc, state, block):
    row = await asyncio.to_thread(source, doc, state, block)
    if os.getenv("SSH_CONNECTION"):
        raise RuntimeError("Remote clipboard transport is not configured")
    if row.image:
        image = await asyncio.to_thread(doc.asset, state["path"], *row.image)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        data, mime = stream.getvalue(), "image/png"
    else:
        data, mime = row.text.plain.encode(), "text/plain;charset=utf-8"
    if shutil.which("wl-copy") and os.getenv("WAYLAND_DISPLAY"):
        argv = ["wl-copy", "--type", mime]
    elif shutil.which("xclip") and os.getenv("DISPLAY"):
        argv = ["xclip", "-selection", "clipboard", "-t", mime]
    else:
        raise RuntimeError("Clipboard requires wl-copy or xclip on the display host")
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, error = await asyncio.wait_for(process.communicate(data), 5)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("Clipboard timed out") from None
    if process.returncode:
        raise RuntimeError(error.decode(errors="replace")[:160] or "Clipboard failed")
