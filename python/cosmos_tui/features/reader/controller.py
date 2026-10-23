import asyncio
import base64
import fcntl
import json
import struct
import sys
import termios
from pathlib import Path

from cosmos_tui.core.controller import Controller
from cosmos_tui.features.reader.layout import Reader
from cosmos_tui.features.reader.loading import LoadingFrames
from cosmos_tui.features.reader.media import Media
from cosmos_tui.features.reader.documents import Documents, FORMATS as DOCUMENTS
from cosmos_tui.features.reader.jump import PageJump
from cosmos_tui.features.search.bar import BottomSearch
from cosmos_tui.input import keymap
from cosmos_tui.render.surface import TerminalSurface
from cosmos_tui.ui.help import Help


class ReaderController(Controller):
    def __init__(self, app):
        super().__init__(app)
        self.media = Media()
        self.loading = LoadingFrames(self)
        self.reader = Reader(self.media)
        self.documents = Documents(self.media, self.reader)
        self.frames = {}
        self.pages = {}
        self.revisions = {}
        self.drag = None
        self.pixel_cell = None
        self.searches = {}
        self.prefetch_task = None
        self.prefetch_request = None
        self.prefetch_token = None
        self.prepared_paths = {}
        self.frame_keys = {}

    def state(self, pane):
        from cosmos_tui.features.reader.preferences import defaults

        return defaults(json.loads(base64.b64decode(pane.viewer)), self.app.settings)

    def pane_bounds(self, pid, path):
        for pane in self.app.panes:
            if pane.id == pid and pane.viewer:
                state = self.state(pane)
                if state["path"] == path:
                    return pane.x, pane.y, pane.width, pane.height
        return None

    def open_pdf_search(self, pane, state):
        app = self.app
        pid = pane.id

        async def search(query, step):
            return await self.search_document(pid, state["path"], query, step)

        app.push_screen(
            BottomSearch(
                "Document"
                if Path(state["path"]).suffix.lower() in DOCUMENTS
                else "PDF",
                search,
                initial=state.get("query", ""),
                steps=True,
                bounds=lambda: self.pane_bounds(pid, state["path"]),
            )
        )

    async def search_document(self, pid, path, query, step):
        app = self.app
        target = next((p for p in app.panes if p.id == pid and p.viewer), None)
        if not target:
            raise RuntimeError("Source document pane is no longer available")
        current = json.loads(base64.b64decode(target.viewer))
        if current["path"] != path:
            raise RuntimeError("Source document changed; reopen search")
        if Path(current["path"]).suffix.lower() in DOCUMENTS:
            return await self.search_rich(target, current, query, step)
        if Path(current["path"]).suffix.lower() != ".pdf":
            return "No text layer in this image"
        if current["path"] != path:
            raise RuntimeError("Source document changed; reopen search")
        current["query"] = query
        if not query:
            self.searches.pop(pid, None)
            current.pop("active_match", None)
            await self.update_viewer(target, current)
            return "Search cleared"
        identity = await asyncio.to_thread(self.media.identity, current["path"])
        cached = self.searches.get(pid)
        if not cached or cached["key"] != (identity, query):
            results, has_text = await asyncio.to_thread(
                self.media.search, current["path"], query
            )
            cached = dict(
                key=(identity, query), results=results, index=-1, has_text=has_text
            )
            self.searches[pid] = cached
        # Verify the captured source again after text extraction.
        target = next(
            (
                p
                for p in app.panes
                if p.id == pid
                and p.viewer
                and json.loads(base64.b64decode(p.viewer))["path"] == current["path"]
            ),
            None,
        )
        if not target:
            raise RuntimeError("Source document is no longer available")
        results = cached["results"]
        if not results:
            await self.update_viewer(target, current)
            return "No matches" if cached["has_text"] else "No text layer"
        if cached["index"] < 0 or not step:
            cached["index"] = next(
                (
                    i
                    for i, item in enumerate(results)
                    if item["page"] >= current.get("page", 1)
                ),
                0,
            )
        else:
            cached["index"] = (cached["index"] + step) % len(results)
        match = results[cached["index"]]
        current["page"] = match["page"]
        current["active_match"] = sum(
            1 for item in results[: cached["index"]] if item["page"] == match["page"]
        )
        current["pan"] = [0, 0]
        current.pop("outline_scroll", None)
        await self.update_viewer(target, current)
        return f"{cached['index'] + 1}/{len(results)} · page {match['page']}"

    def document_info(self, pane, state):
        return (
            self.documents.info(pane, state)
            if Path(state["path"]).suffix.lower() in DOCUMENTS
            else self.media.info(state["path"])
        )

    async def search_rich(self, pane, state, query, step):
        state["query"] = query
        if not query:
            self.searches.pop(pane.id, None)
            await self.update_viewer(pane, state)
            return "Search cleared"
        identity = await asyncio.to_thread(self.media.identity, state["path"])
        cache_key = (
            identity,
            query,
            pane.width,
            pane.height,
            state.get("columns", "auto"),
            tuple(state.get("collapsed_images", [])),
            self.cell_pixels(),
        )
        cached = self.searches.get(pane.id)
        if not cached or cached["key"] != cache_key:
            results = await asyncio.to_thread(self.documents.search, pane, state, query)
            cached = dict(key=cache_key, results=results, index=-1)
            self.searches[pane.id] = cached
        results = cached["results"]
        current = next(
            (
                p
                for p in self.app.panes
                if p.id == pane.id
                and p.viewer
                and json.loads(base64.b64decode(p.viewer))["path"] == state["path"]
            ),
            None,
        )
        if not current:
            raise RuntimeError("Source document changed; reopen search")
        pane = current
        if not results:
            await self.update_viewer(pane, state)
            return "No matches"
        cached["index"] = (
            (cached["index"] + step) % len(results)
            if cached["index"] >= 0 and step
            else 0
        )
        state["page"] = results[cached["index"]]["page"]
        state["row"] = results[cached["index"]]["line"]
        await self.update_viewer(pane, state)
        return f"{cached['index'] + 1}/{len(results)} · page {state['page']}"

    async def open_jump(self, pane, state):
        pid, path = pane.id, state["path"]

        async def jump(page):
            target = next((p for p in self.app.panes if p.id == pid and p.viewer), None)
            if not target:
                raise RuntimeError("Source document pane is no longer available")
            current = json.loads(base64.b64decode(target.viewer))
            if current["path"] != path:
                raise RuntimeError("Source document changed")
            current.update(page=page, pan=[0, 0])
            if Path(path).suffix.lower() in DOCUMENTS:
                from cosmos_tui.features.reader.flow import geometry

                _, _, height, columns = geometry(target, current)
                current["row"] = (page - 1) * height * columns
            current.pop("outline_scroll", None)
            current.pop("outline_index", None)
            await self.update_viewer(target, current)

        if pid not in self.pages:
            self.pages[pid] = (
                await asyncio.to_thread(self.document_info, pane, state)
            )[0]
        self.app.push_screen(
            PageJump(
                state.get("page", 1),
                self.pages.get(pid, 1),
                jump,
                bounds=lambda: self.pane_bounds(pid, path),
            )
        )

    def clear_cache(self):
        self.loading.clear()
        self.prefetch_token = None
        self.prefetch_request = None
        self.media.release()
        self.reader.cache.clear()
        self.documents.clear()
        self.reader.directories.clear()
        self.frames.clear()
        self.frame_keys.clear()
        self.searches.clear()

    async def close(self):
        await self.loading.close()
        self.clear_cache()
        if self.prefetch_task:
            self.prefetch_task.cancel()
            try:
                await self.prefetch_task
            except asyncio.CancelledError:
                pass
            self.prefetch_task = None

    def schedule_prefetch(self, pane, state, pages):
        if not self.app.settings.get("viewer_prefetch", True):
            self.prefetch_token = None
            self.prefetch_request = None
            return
        if Path(state["path"]).suffix.lower() != ".pdf":
            return
        token = (
            pane.id,
            state["path"],
            state.get("page", 1),
            self.media.identity(state["path"]),
        )
        if token == self.prefetch_token:
            return
        self.prefetch_token = token
        self.prefetch_request = (token, dict(state), pages)
        if self.prefetch_task is None or self.prefetch_task.done():
            self.prefetch_task = asyncio.create_task(self.prefetch())

    async def prefetch(self):
        while self.prefetch_request:
            token, state, pages = self.prefetch_request
            self.prefetch_request = None
            current = state.get("page", 1)
            for number in (current - 1, current + 1):
                if self.prefetch_token != token:
                    break
                if 1 <= number <= pages:
                    try:
                        await asyncio.to_thread(
                            self.media.load, dict(state, page=number, query="")
                        )
                    except (OSError, ValueError, RuntimeError):
                        continue
            for number in range(max(1, current - 3), min(pages, current + 3) + 1):
                if self.prefetch_token != token:
                    break
                try:
                    await asyncio.to_thread(
                        self.media.thumbnail,
                        dict(state, page=number, query=""),
                        (256, 128),
                    )
                except (OSError, ValueError, RuntimeError):
                    continue

    def sync_visible(self, panes):
        visible = {p.id for p in panes if p.viewer}
        self.loading.prune(visible)
        for pid in list(self.frames):
            if pid not in visible:
                self.frames.pop(pid, None)
                self.pages.pop(pid, None)
                self.searches.pop(pid, None)
                self.prepared_paths.pop(pid, None)
                self.frame_keys.pop(pid, None)
        if self.prefetch_token and self.prefetch_token[0] not in visible:
            self.prefetch_token = None
            self.prefetch_request = None
        if not visible and getattr(self, "_had_viewers", False):
            self.clear_cache()
        self._had_viewers = bool(visible)

    def cell_pixels(self):
        if self.pixel_cell:
            return self.pixel_cell
        try:
            rows, cols, width, height = struct.unpack(
                "HHHH",
                fcntl.ioctl(sys.__stdin__.fileno(), termios.TIOCGWINSZ, b"\0" * 8),
            )
            if rows and cols and width and height:
                return max(1, round(width / cols)), max(1, round(height / rows))
        except (OSError, ValueError, AttributeError):
            pass
        return 8, 16

    def view_scale(self, pane, state, frame):
        cw, ch = self.cell_pixels()
        sw, sh = frame.source_size
        return max(
            0.001,
            min(frame.main_cols * cw / sw, frame.main_rows * ch / sh)
            * state.get("zoom", 1),
        )

    async def update_viewer(self, pane, state):
        app = self.app
        if Path(state["path"]).suffix.lower() in DOCUMENTS:
            state["_cell"] = self.cell_pixels()
        frame = self.frames.get(pane.id)
        if frame and Path(state["path"]).suffix.lower() not in DOCUMENTS:
            # Clamp in source pixels after every input, not just while rasterizing.
            cw, ch = self.cell_pixels()
            sw, sh = frame.source_size
            scale = min(
                frame.main_cols * cw / sw, frame.main_rows * ch / sh
            ) * state.get("zoom", 1)
            limits = (
                max(0, (sw - frame.main_cols * cw / scale) / 2),
                max(0, (sh - frame.main_rows * ch / scale) / 2),
            )
            state["pan"] = [
                max(-limit, min(limit, value))
                for value, limit in zip(state.get("pan", [0, 0]), limits)
            ]
        wire = base64.b64encode(json.dumps(state).encode()).decode()
        self.revisions[pane.id] = self.revisions.get(pane.id, 0) + 1
        await app.backend.request(f"set-option -p -t {pane.id} @cosmos_viewer {wire}")
        pane.viewer = wire

    def viewer_at(self, event):
        app = self.app
        if app.screen is not app._workspace_screen:
            return None
        return next(
            (
                p
                for p in app.panes
                if p.viewer
                and p.x <= event.screen_x < p.x + p.width
                and p.y <= event.screen_y < p.y + p.height
            ),
            None,
        )

    async def on_mouse_down(self, event):
        app = self.app
        pane = self.viewer_at(event)
        if not pane or event.button != 1:
            return
        frame = self.frames.get(pane.id)
        if not frame:
            return
        event.stop()
        state = self.state(pane)
        x, y = event.screen_x - pane.x, event.screen_y - pane.y
        for left, top, width, height, index in reversed(frame.hits):
            if left <= x < left + width and top <= y < top + height:
                if (
                    isinstance(index, tuple)
                    and Path(state["path"]).suffix.lower() in DOCUMENTS
                ):
                    from cosmos_tui.features.reader.rich_input import action

                    await action(self, pane, state, *index[:2])
                    return
                if isinstance(index, tuple):
                    state.update(
                        page=index[1],
                        pan=[0, 0],
                        outline_index=index[2] if len(index) > 2 else 0,
                        nav_focus=False,
                    )
                elif index == -2:
                    state["navigation"] = (
                        "thumbnails"
                        if state.get("navigation") == "outline"
                        else "outline"
                    )
                elif index < 0:
                    state["thumbnails"] = not state.get("thumbnails", True)
                else:
                    state = self.reader.change(state, index, frame.entries)
                await self.update_viewer(pane, state)
                return
        if Path(state["path"]).suffix.lower() in DOCUMENTS:
            if state.get("inspector") is not None:
                from cosmos_tui.features.reader.inspector import source

                if (
                    source(self.documents, state, state["inspector"]).image
                    and y < frame.main_rows
                ):
                    self.drag = pane.id, event.screen_x, event.screen_y
                    app.query_one(TerminalSurface).capture_mouse()
            return
        if y < frame.main_rows and x >= frame.main_x:
            self.drag = pane.id, event.screen_x, event.screen_y
            app.query_one(TerminalSurface).capture_mouse()

    async def on_mouse_move(self, event):
        app = self.app
        if not self.drag:
            pane = self.viewer_at(event)
            if (
                pane
                and Path(
                    json.loads(base64.b64decode(pane.viewer))["path"]
                ).suffix.lower()
                in DOCUMENTS
            ):
                state = self.state(pane)
                frame = self.frames.get(pane.id)
                hit = next(
                    (
                        list(item[:2])
                        for x, y, w, h, item in reversed(frame.hits if frame else [])
                        if isinstance(item, tuple)
                        and x <= event.screen_x - pane.x < x + w
                        and y <= event.screen_y - pane.y < y + h
                    ),
                    None,
                )
                if state.get("hover") != hit:
                    state["hover"] = hit
                    await self.update_viewer(pane, state)
            return
        pid, x, y = self.drag
        pane = next((p for p in app.panes if p.id == pid and p.viewer), None)
        if pane:
            frame = self.frames.get(pid)
            state = self.state(pane)
            cw, ch = self.cell_pixels()
            if Path(state["path"]).suffix.lower() in DOCUMENTS:
                if state.get("inspector") is None:
                    return
                from cosmos_tui.features.reader.inspector import source

                row = source(self.documents, state, state["inspector"])
                if not row.image:
                    return
                image = await asyncio.to_thread(
                    self.documents.asset, state["path"], *row.image
                )
                scale, pan = self.media.geometry(
                    image,
                    dict(
                        zoom=state.get("inspect_zoom", 1),
                        pan=state.get("inspect_pan", [0, 0]),
                    ),
                    pane.width * cw,
                    max(1, pane.height - 1) * ch,
                )
                state["inspect_pan"] = [
                    pan[0] - (event.screen_x - x) * cw / scale,
                    pan[1] - (event.screen_y - y) * ch / scale,
                ]
                self.drag = pid, event.screen_x, event.screen_y
                await self.update_viewer(pane, state)
                event.stop()
                return
            state["pan"] = [
                state["pan"][0]
                - (event.screen_x - x) * cw / self.view_scale(pane, state, frame),
                state["pan"][1]
                - (event.screen_y - y) * ch / self.view_scale(pane, state, frame),
            ]
            self.drag = pid, event.screen_x, event.screen_y
            await self.update_viewer(pane, state)
            event.stop()

    def on_mouse_up(self, event):
        app = self.app
        if self.drag:
            self.drag = None
            app.query_one(TerminalSurface).release_mouse()
            event.stop()

    async def scroll_viewer(self, event, direction):
        pane = self.viewer_at(event)
        if not pane:
            return
        frame = self.frames.get(pane.id)
        if not frame:
            return
        state = self.state(pane)
        if (
            Path(state["path"]).suffix.lower() in DOCUMENTS
            and state.get("inspector") is not None
        ):
            from cosmos_tui.features.reader.rich_input import key
            from types import SimpleNamespace

            await key(
                self,
                SimpleNamespace(
                    key="plus" if direction < 0 else "minus",
                    character="+" if direction < 0 else "-",
                )
                if event.ctrl
                else SimpleNamespace(
                    key="up" if direction < 0 else "down", character=None
                ),
                pane,
                state,
            )
            event.stop()
            return
        if Path(state["path"]).suffix.lower() in DOCUMENTS and not event.ctrl:
            if event.screen_x - pane.x < frame.main_x:
                outline = await asyncio.to_thread(
                    lambda: self.document_info(pane, state)[1]
                )
                state["outline_scroll"] = max(
                    0,
                    min(
                        max(0, len(outline) - frame.main_rows + 1),
                        state.get("outline_scroll", 0) + direction,
                    ),
                )
                await self.update_viewer(pane, state)
                event.stop()
                return
            from cosmos_tui.features.reader.rich_input import key
            from types import SimpleNamespace

            await key(
                self,
                SimpleNamespace(key="up" if direction < 0 else "down", character=None),
                pane,
                state,
            )
            event.stop()
            return
        if (
            state.get("navigation") == "outline"
            and event.screen_x - pane.x < frame.main_x
        ):
            outline = await asyncio.to_thread(
                lambda: self.document_info(pane, state)[1]
            )
            state["outline_scroll"] = max(
                0,
                min(
                    max(0, len(outline) - frame.main_rows + 1),
                    int(state.get("outline_scroll", 0)) + direction,
                ),
            )
            await self.update_viewer(pane, state)
            event.stop()
            return
        entries, selected = self.reader.collection(state, self.pages.get(pane.id, 1))
        if not event.ctrl and len(entries) > 1:
            state = self.reader.change(state, selected + direction, entries)
        else:
            old_scale = self.view_scale(pane, state, frame)
            state["zoom"] = min(
                8, max(0.25, state["zoom"] * (1.25 if direction < 0 else 1 / 1.25))
            )
            new_scale = (
                old_scale
                * state["zoom"]
                / json.loads(base64.b64decode(pane.viewer))["zoom"]
            )
            cw, ch = self.cell_pixels()
            dx, dy = (
                (event.screen_x - pane.x - frame.main_x + 0.5 - frame.main_cols / 2)
                * cw,
                (event.screen_y - pane.y + 0.5 - frame.main_rows / 2) * ch,
            )
            state["pan"] = [
                state["pan"][0] + dx * (1 / old_scale - 1 / new_scale),
                state["pan"][1] + dy * (1 / old_scale - 1 / new_scale),
            ]
        await self.update_viewer(pane, state)
        event.stop()

    async def on_key(self, event, pane):
        app = self.app
        state = self.state(pane)
        if Path(state["path"]).suffix.lower() in DOCUMENTS:
            from cosmos_tui.features.reader.rich_input import key

            if await key(self, event, pane, state):
                return
        if event.key in ("q", "escape"):
            self.revisions[pane.id] = self.revisions.get(pane.id, 0) + 1
            self.frames.pop(pane.id, None)
            self.pages.pop(pane.id, None)
            self.searches.pop(pane.id, None)
            self.clear_cache()
            pane.viewer = ""
            await app.backend.request(f"set-option -pu -t {pane.id} @cosmos_viewer")
            return
        elif event.character == "?":
            app.push_screen(Help("Viewer", keymap.help_rows("viewer", app.settings)))
            return
        elif event.character == "g" and Path(
            state["path"]
        ).suffix.lower() in DOCUMENTS | {".pdf"}:
            await self.open_jump(pane, state)
            return
        elif event.character == "o" and Path(
            state["path"]
        ).suffix.lower() in DOCUMENTS | {".pdf"}:
            state["navigation"] = (
                "thumbnails" if state.get("navigation") == "outline" else "outline"
            )
            state["thumbnails"] = True
        elif event.character in ("n", "N") and state.get("query"):
            await self.search_document(
                pane.id,
                state["path"],
                state["query"],
                1 if event.character == "n" else -1,
            )
            return
        elif event.character == "/":
            self.open_pdf_search(pane, state)
            return
        elif event.key == "tab" and state.get("navigation") == "outline":
            state["nav_focus"] = not state.get("nav_focus", False)
        elif (
            state.get("nav_focus")
            and state.get("navigation") == "outline"
            and event.key in ("up", "down", "enter", "pageup", "pagedown")
        ):
            outline = await asyncio.to_thread(
                lambda: self.document_info(pane, state)[1]
            )
            if outline:
                selected = int(
                    state.get(
                        "outline_index",
                        max(
                            (
                                i
                                for i, item in enumerate(outline)
                                if item["page"] <= state.get("page", 1)
                            ),
                            default=0,
                        ),
                    )
                )
                selected = max(0, min(len(outline) - 1, selected))
                if event.key == "enter":
                    state.update(
                        page=outline[selected]["page"], pan=[0, 0], nav_focus=False
                    )
                else:
                    delta = -1 if event.key in ("up", "pageup") else 1
                    if event.key in ("pageup", "pagedown"):
                        delta *= max(1, pane.height - 2)
                    state["outline_index"] = max(
                        0, min(len(outline) - 1, selected + delta)
                    )
                    state["outline_scroll"] = max(
                        0, state["outline_index"] - max(1, pane.height - 2) // 2
                    )
        elif event.character in ("+", "=", "-"):
            state["zoom"] = min(
                8,
                max(
                    0.25,
                    state["zoom"] * (1 / 1.25 if event.character == "-" else 1.25),
                ),
            )
        elif event.character == "t":
            state["thumbnails"] = not state.get("thumbnails", True)
        elif event.character == "0":
            state["zoom"] = 1
            state["pan"] = [0, 0]
        elif event.character in ("[", "]"):
            entries, selected = self.reader.collection(
                state, self.pages.get(pane.id, 1)
            )
            state = self.reader.change(
                state, selected + (1 if event.character == "]" else -1), entries
            )
        elif event.key in ("up", "down", "left", "right"):
            frame = self.frames.get(pane.id)
            if frame:
                i = 0 if event.key in ("left", "right") else 1
                cw, ch = self.cell_pixels()
                state["pan"][i] += (
                    4 * (cw if i == 0 else ch) / self.view_scale(pane, state, frame)
                ) * (1 if event.key in ("right", "down") else -1)
        await self.update_viewer(pane, state)

    async def prepare(self, pane):
        app = self.app
        state = self.state(pane)
        state["_cell"] = self.cell_pixels()
        revision = self.revisions.get(pane.id, 0)
        budget = app.settings.get("viewer_cache_mb", 128)
        self.media.configure(budget)
        await asyncio.to_thread(
            self.media.disk.configure, app.settings.get("viewer_disk_cache_mb", 512)
        )
        pdf_policy = (
            app.settings.get("viewer_pdf_edge", 2400),
            app.settings.get("viewer_pdf_page_mb", 32),
        )
        if pdf_policy != (self.media.pdf_edge, self.media.pdf_page_mb):
            self.media.release()
            self.reader.cache.clear()
            self.frame_keys.clear()
            self.media.pdf_edge, self.media.pdf_page_mb = pdf_policy
        self.media.image_max_mb = app.settings.get("viewer_image_max_mb", 32)
        self.reader.cache.resize(int(budget * 1024**2 * 0.2))
        identity = await asyncio.to_thread(self.media.identity, state["path"])
        if self.prepared_paths.get(pane.id) not in (None, identity):
            self.reader.cache.clear()
            self.frames.pop(pane.id, None)
            self.searches.pop(pane.id, None)
            self.prefetch_token = None
        self.prepared_paths[pane.id] = identity

        def signature():
            return (
                identity,
                repr(state),
                pane.width,
                pane.height,
                self.cell_pixels(),
                tuple(app.role_colors.items()),
                app.graphics.enabled,
                self.media.revision,
                self.media.image_max_mb,
            )

        if (
            self.frames.get(pane.id) is not None
            and self.frame_keys.get(pane.id) == signature()
        ):
            self.schedule_prefetch(pane, state, self.pages[pane.id])
            return self.frames[pane.id]
        if Path(state["path"]).suffix.lower() in DOCUMENTS:
            frame, pages = await asyncio.to_thread(
                self.documents.render, pane, state, app.role_colors, self.cell_pixels()
            )
            if revision != self.revisions.get(pane.id, 0):
                return
            self.frames[pane.id], self.pages[pane.id] = frame, pages
            self.frame_keys[pane.id] = signature()
            return frame
        page = max(1, int(state.get("page", 1)))
        if self.media.cache.get(identity + (page,)) is None:
            self.loading.missing[pane.id] = self.loading.key(pane)
        source, pages, has_text = await asyncio.to_thread(self.media.load, state)
        if state.get("page", 1) > pages:
            state["page"] = pages
            await self.update_viewer(pane, state)
            revision = self.revisions.get(pane.id, 0)
        frame_signature = signature()
        frame = await asyncio.to_thread(
            self.reader.render,
            source,
            state,
            pages,
            pane.width,
            pane.height,
            self.cell_pixels(),
            app.role_colors,
            app.graphics.enabled,
        )
        if revision != self.revisions.get(pane.id, 0):
            return
        self.frame_keys[pane.id] = frame_signature
        self.frames[pane.id] = frame
        self.pages[pane.id] = pages
        self.schedule_prefetch(pane, state, pages)
        if pane.active:
            app.message = ""
        if pane.active and not has_text and str(state["path"]).lower().endswith(".pdf"):
            app.message = "No text layer; OCR is not enabled"
        return frame
