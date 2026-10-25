"""Full file workspace rendered by Cosmos; no child TUI or terminal writes."""

import asyncio
from pathlib import Path

from cosmos_tui.features.files.model import entries
from cosmos_tui.features.files.render import render
from cosmos_tui.features.files.style import metadata
from cosmos_tui.features.search.bar import BottomSearch


class FileManager:
    def __init__(self, controller):
        self.controller = controller
        self.snapshots = {}
        self.clipboard = None
        self.busy = False

    def listing(self, state):
        key = (
            state["path"],
            Path(state["path"]).stat().st_mtime_ns,
            state.get("filter", ""),
            state.get("show_hidden", False),
            state.get("sort", "natural"),
            state.get("reverse", False),
        )
        result = self.snapshots.get(key)
        if result is None:
            result = entries(state)
            if len(self.snapshots) >= 8:
                self.snapshots.clear()
            self.snapshots[key] = result
        return result

    def render(self, pane, state, palette, cell):
        return render(self, pane, state, palette, cell)

    def status(self, state):
        return metadata(self.listing(state), state.get("cursor", 0))

    async def key(self, event, pane, state):
        controller = self.controller
        key, char = event.key, event.character
        if key in ("q", "escape"):
            controller.preview.release(pane.id)
            pane.viewer = ""
            controller.frames.pop(pane.id, None)
            await controller.app.backend.request(
                f"set-option -pu -t {pane.id} @cosmos_viewer"
            )
            return
        items = await asyncio.to_thread(self.listing, state)
        cursor = max(0, min(len(items) - 1, state.get("cursor", 0)))
        from cosmos_tui.features.files.actions import handle

        if await handle(self, event, pane, state, items, cursor):
            return
        if char == "?":
            from cosmos_tui.ui.help import Help
            from cosmos_tui.input import keymap

            controller.app.push_screen(
                Help("Files", keymap.help_rows("files", controller.app.settings))
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
            origin = state["path"]
            state.update(
                path=str(Path(origin).parent), cursor=0, filter="", selected=[]
            )
            parents = await asyncio.to_thread(self.listing, state)
            state["cursor"] = next(
                (i for i, item in enumerate(parents) if item["path"] == origin), 0
            )
        elif key in ("right", "enter") and items:
            item = items[cursor]
            if item["directory"]:
                state.update(path=item["path"], cursor=0, filter="", selected=[])
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
            sorts = ["natural", "size", "mtime", "extension"]
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
