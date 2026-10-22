"""Pane-local reading stage and collapsible image/document thumbnail navigation."""

import itertools
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw
from rich.text import Text

from cosmos_tui.render.graphics import halfblocks

FORMATS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class ReadingFrame:
    image: Image.Image
    lines: list[Text]
    entries: object
    selected: int
    hits: list
    main_rows: int
    main_x: int
    main_cols: int
    scale: float
    source_size: tuple
    pan: tuple


class Reader:
    def __init__(self, media):
        self.media = media
        self.directories = {}
        self.cache = {}

    def collection(self, state, pages):
        path = Path(state["path"])
        if path.suffix.lower() == ".pdf":
            return range(1, pages + 1), max(
                0, min(pages - 1, int(state.get("page", 1)) - 1)
            )
        directory = path.parent
        stamp = directory.stat().st_mtime_ns
        key = str(directory), stamp
        if key not in self.directories:
            files = [
                p
                for p in itertools.islice(directory.iterdir(), 10000)
                if p.suffix.lower() in FORMATS and p.is_file()
            ]
            files = sorted(files, key=lambda p: p.name.casefold())
            if path not in files:
                files.append(path)
            if len(self.directories) >= 8:
                self.directories.pop(next(iter(self.directories)))
            self.directories[key] = files
        files = self.directories[key]
        return files, files.index(path)

    @staticmethod
    def change(state, index, entries):
        index = max(0, min(len(entries) - 1, index))
        state = dict(state)
        if Path(state["path"]).suffix.lower() == ".pdf":
            state["page"] = entries[index]
        else:
            state.update(path=str(entries[index]), page=1, zoom=1, pan=[0, 0], query="")
        return state

    def render(self, source, state, pages, cols, rows, cell, palette, graphics):
        entries, selected = self.collection(state, pages)
        document = Path(state["path"]).suffix.lower() == ".pdf"
        navigation_key = pages if document else tuple(map(str, entries))
        key = (
            id(source),
            repr(state),
            cols,
            rows,
            cell,
            tuple(palette.items()),
            graphics,
            navigation_key,
        )
        if key in self.cache:
            return self.cache[key][1]
        cw, ch = cell
        expanded = state.get("thumbnails", True) and rows >= 12 and cols >= 30
        sidebar = min(18, cols // 5) if document and expanded else 0
        footer = 6 if expanded and not document else 1 if rows >= 3 else 0
        main_rows = max(1, rows - footer)
        main_cols = max(1, cols - sidebar)
        width, height = main_cols * cw, main_rows * ch
        if cols * cw * rows * ch > 16_000_000:
            raise ValueError("reading viewport exceeds 16 million pixels")
        scale, pan = self.media.geometry(source, state, width, height)
        stage = self.media.viewport(source, state, width, height, palette["bg"])
        canvas = Image.new("RGB", (cols * cw, rows * ch), palette["base"])
        canvas.paste(stage, (sidebar * cw, 0))
        lines = [Text(" " * cols, style=f"on {palette['bg']}") for _ in range(rows)]
        hits, labels, boxes = [], {}, []
        if footer:
            info = Text(
                f" {Path(state['path']).name}  {selected + 1}/{len(entries)}  {float(state.get('zoom', 1)):.2f}×  {source.width}×{source.height}",
                style=f"{palette['fg']} on {palette['base']}",
            )
            info.truncate(max(1, cols - 3), overflow="ellipsis")
            info.pad_right(max(0, cols - 3 - info.cell_len))
            info.append(" − " if expanded else " + ", style=palette["accl"])
            labels[main_rows] = (0, info)
            hits.append((cols - 3, main_rows, 3, 1, -1))
        if expanded:
            slots = min(
                len(entries),
                min(7, max(1, main_rows // 5))
                if document
                else min(5, max(1, cols // 12)),
            )
            start = max(0, min(selected - slots // 2, len(entries) - slots))
            for slot, index in enumerate(range(start, start + slots)):
                x, y, w = (
                    (0, slot * 5, sidebar)
                    if document
                    else (slot * (cols // slots), main_rows + 1, cols // slots)
                )
                boxes.append((x, y, w, 4, index))
        draw = ImageDraw.Draw(canvas)
        for x, y, w, h, index in boxes:
            tw, th = w * cw, h * ch
            thumb_state = self.change(state, index, entries)
            try:
                thumb = self.media.thumbnail(
                    thumb_state, (max(1, tw - 8), max(1, th - 8))
                )
                tx, ty = (
                    x * cw + (tw - thumb.width) // 2,
                    y * ch + (th - thumb.height) // 2,
                )
                canvas.paste(thumb, (tx, ty))
                if index == selected:
                    sw, sh = source.size
                    left, top = (
                        sw / 2 + pan[0] - width / scale / 2,
                        sh / 2 + pan[1] - height / scale / 2,
                    )
                    right, bottom = left + width / scale, top + height / scale
                    draw.rectangle(
                        (
                            tx + max(0, left) / sw * thumb.width,
                            ty + max(0, top) / sh * thumb.height,
                            tx + min(sw, right) / sw * thumb.width - 1,
                            ty + min(sh, bottom) / sh * thumb.height - 1,
                        ),
                        outline=palette["accl"],
                        width=1,
                    )
            except (OSError, ValueError, RuntimeError):
                pass
            if index == selected:
                draw.rectangle(
                    (x * cw, y * ch, (x + w) * cw - 1, (y + h) * ch - 1),
                    outline=palette["acc"],
                    width=2,
                )
            hits.append((x, y, w, 5, index))
            label = (
                f" {index + 1}" if document else f" {index + 1} {entries[index].name}"
            )
            text = Text(
                label,
                style=f"{palette['accl'] if index == selected else palette['mute']} on {palette['base']}",
            )
            text.truncate(w, overflow="ellipsis")
            text.pad_right(max(0, w - text.cell_len))
            if y + h in labels:
                labels[y + h][1].append_text(text)
            else:
                labels[y + h] = (x, text)
        if not graphics:
            lines = halfblocks(canvas, cols, rows)
        for row, (x, text) in labels.items():
            line = lines[row]
            lines[row] = line[:x] + text + line[x + text.cell_len :]
        frame = ReadingFrame(
            canvas,
            lines,
            entries,
            selected,
            hits,
            main_rows,
            sidebar,
            main_cols,
            scale,
            source.size,
            pan,
        )
        if len(self.cache) >= 3:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = source, frame
        return frame
