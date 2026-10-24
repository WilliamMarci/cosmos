"""Full file workspace rendered by Cosmos; no child TUI or terminal writes."""

import asyncio
from pathlib import Path

from PIL import Image, ImageDraw
from rich.text import Text
from cosmos_tui.features.files.model import entries, preview, display
from cosmos_tui.features.reader.layout import ReadingFrame
from cosmos_tui.features.reader.flow import put
from cosmos_tui.features.search.bar import BottomSearch


class FileManager:
    def __init__(self, controller):
        self.controller = controller
        self.snapshots = {}

    def listing(self, state):
        key = (
            state["path"],
            Path(state["path"]).stat().st_mtime_ns,
            state.get("filter", ""),
            state.get("show_hidden", False),
            state.get("sort", "natural"),
        )
        if key not in self.snapshots:
            result = entries(state)
            if len(self.snapshots) >= 8:
                self.snapshots.clear()
            self.snapshots[key] = result
        return self.snapshots[key]

    def render(self, pane, state, palette, cell):
        items = self.listing(state)
        cw, ch = cell
        canvas = Image.new("RGB", (pane.width * cw, pane.height * ch), palette["bg"])
        lines = [
            Text(" " * pane.width, style=f"{palette['fg']} on {palette['bg']}")
            for _ in range(pane.height)
        ]
        rows = max(1, pane.height - 2)
        cursor = max(0, min(len(items) - 1, state.get("cursor", 0)))
        left = pane.width if pane.width < 65 else pane.width * 3 // 5
        put(
            lines,
            0,
            0,
            Text(" " + display(state["path"]), style=palette["accl"]),
            pane.width,
        )
        top = max(0, min(cursor - rows // 2, max(0, len(items) - rows)))
        hits = []
        draw = ImageDraw.Draw(canvas)
        for y, index in enumerate(range(top, min(len(items), top + rows)), 1):
            item = items[index]
            selected = index == cursor
            bg = palette["acc"] if selected else palette["bg"]
            fg = (
                palette["on"]
                if selected
                else palette["accl"]
                if item["directory"]
                else palette["fg"]
            )
            if selected:
                draw.rectangle((0, y * ch, left * cw - 1, (y + 1) * ch - 1), fill=bg)
            label = (
                " "
                + display(item["name"])
                + ("/" if item["directory"] else "")
                + (" ↗" if item["link"] else "")
            )
            text = Text(label, style=f"{fg} on {bg}")
            text.truncate(max(1, left - 1), overflow="ellipsis")
            put(lines, 0, y, text, left)
            hits.append((0, y, left, 1, ("file_entry", index)))
        if not items:
            put(
                lines,
                1,
                1,
                Text("No matching files", style=palette["mute"]),
                max(1, left - 2),
            )
        if left < pane.width:
            draw.line(
                (left * cw, ch, left * cw, (pane.height - 1) * ch), fill=palette["mute"]
            )
            if items:
                try:
                    content = preview(items[cursor])
                except OSError as error:
                    content = str(error)
                for y, line in enumerate(content.splitlines()[:rows], 1):
                    put(
                        lines,
                        left + 2,
                        y,
                        Text(display(line.expandtabs(4)), style=palette["mute"]),
                        max(0, pane.width - left - 3),
                    )
        footer = f" {len(items)} entries · {state.get('sort', 'natural')}" + (
            " · hidden" if state.get("show_hidden") else ""
        )
        lines[-1] = Text(footer, style=f"{palette['fg']} on {palette['base']}")
        lines[-1].truncate(pane.width)
        return ReadingFrame(
            canvas, lines, items, cursor, hits, rows, 0, left, 1, canvas.size, (0, 0)
        )

    async def key(self, event, pane, state):
        controller = self.controller
        items = await asyncio.to_thread(self.listing, state)
        key, char = event.key, event.character
        cursor = max(0, min(len(items) - 1, state.get("cursor", 0)))
        if char == "?":
            from cosmos_tui.ui.help import Help
            from cosmos_tui.input import keymap

            controller.app.push_screen(
                Help("Files", keymap.help_rows("files", controller.app.settings))
            )
            return
        if key in ("q", "escape"):
            pane.viewer = ""
            controller.frames.pop(pane.id, None)
            await controller.app.backend.request(
                f"set-option -pu -t {pane.id} @cosmos_viewer"
            )
            return
        if key in ("up", "down", "home", "end", "pageup", "pagedown"):
            step = max(1, pane.height - 2) if key in ("pageup", "pagedown") else 1
            state["cursor"] = (
                0
                if key == "home"
                else max(0, len(items) - 1)
                if key == "end"
                else max(
                    0,
                    min(
                        len(items) - 1,
                        cursor + (-step if key in ("up", "pageup") else step),
                    ),
                )
            )
        elif key == "left":
            state.update(path=str(Path(state["path"]).parent), cursor=0, filter="")
        elif key in ("right", "enter") and items:
            item = items[cursor]
            if item["directory"]:
                state.update(path=item["path"], cursor=0, filter="")
            else:
                from cosmos_tui.features.reader.opener import SUPPORTED

                if Path(item["path"]).suffix.lower() in SUPPORTED:
                    state = dict(
                        path=item["path"],
                        page=1,
                        zoom=1,
                        pan=[0, 0],
                        query="",
                        return_files=dict(state, cursor=cursor),
                    )
                else:
                    process = await asyncio.create_subprocess_exec(
                        "xdg-open",
                        item["path"],
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, error = await process.communicate()
                    if process.returncode:
                        await controller.app.action_error(
                            "files.open",
                            RuntimeError(error.decode(errors="replace")[:180]),
                        )
                    return
        elif char == ".":
            state["show_hidden"] = not state.get("show_hidden", False)
        elif char == "s":
            sorts = ["natural", "size", "mtime"]
            state["sort"] = sorts[
                (sorts.index(state.get("sort", "natural")) + 1) % len(sorts)
            ]
        elif char == "/":
            pid = pane.id

            async def search(query, step):
                target = next(
                    (p for p in controller.app.panes if p.id == pid and p.viewer), None
                )
                if target is None:
                    raise RuntimeError("File workspace is no longer available")
                current = controller.state(target)
                if current.get("kind") != "files":
                    raise RuntimeError("Source view changed")
                current.update(filter=query, cursor=0)
                await controller.update_viewer(target, current)
                return "Filter applied"

            controller.app.push_screen(
                BottomSearch(
                    "Files",
                    search,
                    initial=state.get("filter", ""),
                    bounds=lambda: controller.pane_bounds(pid, state["path"]),
                )
            )
            return
        if state.get("kind") == "files":
            await asyncio.to_thread(self.listing, state)
        await controller.update_viewer(pane, state)
