"""Session/window/pane tree with stable targets and matching layout preview."""

import asyncio
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, ListItem, ListView, Static
from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.zones import Zone
from cosmos_tui.features.navigation.switch_preview import LayoutPreview, SwitchDivider
from cosmos_tui.features.navigation.switch_rows import SwitchRow
from cosmos_tui.features.navigation.session_prompt import NewSession
from cosmos_tui.ui.menus import CompactMenu
from cosmos_tui.terminal import targets


class Switcher(CosmosModal):
    zone = Zone.POP_WINDOW
    AUTO_FOCUS = "#switch-filter"
    BINDINGS = [Binding("escape", "cancel", show=False)]
    DEFAULT_CSS = """
    Switcher { align: center middle; background: transparent; }
    #switcher { width: 88%; height: 82%; padding: 0; }
    #switch-columns { height: 1fr; }
    #switch-browser { width: 42%; min-width: 18; height: 100%; padding: 0 1; }
    #switch-list { height: 1fr; min-height: 2; margin: 0; }
    #switch-filter { height: 1; border: none; padding: 0; }
    #switch-new { height: 1; width: 100%; }
    LayoutPreview { width: 1fr; height: 100%; }
    """

    def __init__(self):
        super().__init__()
        self.inventory_ready = asyncio.Event()
        self.windows = []
        self.rows = []
        self.pane_meta = {}
        self.expanded = set()
        self.pending = None
        self.preview_busy = False
        self.revision = 0
        self.filter_query = None
        self.refreshing = False
        self.finished = False
        self.populate_lock = asyncio.Lock()

    def compose(self):
        with Frame(id="switcher") as frame:
            frame.set_heading("Switch", "workspace.switch")
            frame.junction_selector = "#switch-divider"
            with Horizontal(id="switch-columns"):
                with Vertical(id="switch-browser"):
                    listing = ListView(id="switch-list")
                    listing.can_focus = False
                    yield listing
                    yield CosmosInput(
                        id="switch-filter", placeholder="Filter name or $ / @ / % ID"
                    )
                    yield Static("＋ New session", id="switch-new", markup=False)
                yield SwitchDivider(id="switch-divider")
                yield LayoutPreview()

    async def on_mount(self):
        self.expanded = getattr(self.app, "_switch_expanded", set())
        self.app._switch_expanded = self.expanded
        palette = self.app.role_colors
        for widget in self.query("#switch-list, #switch-new"):
            widget.styles.background = palette["base"]
            widget.styles.color = palette["accl"]
        try:
            await self.reload(initial=True)
            self.set_focus(self.query_one(Input))
            self.set_interval(0.2, self.refresh_preview)
            self.set_interval(2, self.refresh_inventory)
        except (OSError, RuntimeError, ValueError) as error:
            await self.error(error)
        finally:
            self.inventory_ready.set()

    async def error(self, error):
        if self.finished:
            return
        await self.app.action_error("switch", error)

    async def reload(self, initial=False):
        self.windows = await self.app.backend.inventory()
        if hasattr(self.app.backend, "request"):
            raw = await self.app.backend.request(
                "list-panes -a -F '#{session_id}|#{window_id}|#{pane_id}|#{pane_index}|#{pane_current_command}|#{@cosmos_name}'"
            )
            self.pane_meta = {}
            for line in raw:
                parts = line.split("|", 5)
                if len(parts) == 6:
                    sid, wid, pid, index, program, name = parts
                    self.pane_meta.setdefault(wid, []).append(
                        dict(
                            pane_id=pid,
                            pane_index=int(index),
                            program=program,
                            pane_name=name,
                        )
                    )
        await self.populate()

    def nodes(self, query):
        result = []
        sessions = {}
        for window in self.windows:
            sessions.setdefault(window["session_id"], []).append(window)
        for sid, windows in sessions.items():
            active = next((w for w in windows if w.get("active")), windows[0])
            session = dict(active, kind="session", key=sid)
            children = []
            session_match = query in f"{sid} {active['session']}".casefold()
            for w in windows:
                node = dict(w, kind="window", key=sid + ":" + w["window_id"])
                match = (
                    session_match
                    or query in f"{w['window_id']} {w['index']} {w['name']}".casefold()
                )
                panes = [
                    dict(
                        w,
                        **p,
                        kind="pane",
                        key=sid + ":" + w["window_id"] + ":" + p["pane_id"],
                    )
                    for p in self.pane_meta.get(w["window_id"], [])
                ]
                filtered = [
                    p
                    for p in panes
                    if match
                    or query
                    in f"{p['pane_id']} {p['pane_index']} {p.get('pane_name', '')} {p.get('program', '')}".casefold()
                ]
                if not query or match or filtered:
                    children.append(node)
                    if query or node["key"] in self.expanded:
                        children.extend(filtered if query else panes)
            if not query or session_match or children:
                result.append(session)
                if query or sid in self.expanded:
                    result.extend(children)
        return result

    async def populate(self):
        async with self.populate_lock:
            if not self.finished:
                await self._populate()

    async def _populate(self):
        selected = self.selected()
        previous = selected.get("key") if selected else None
        if previous is None:
            wid = next((t[0] for t in self.app.backend.tabs if t[2] == "1"), None)
            previous = next(
                (
                    w["session_id"] + ":" + w["window_id"]
                    for w in self.windows
                    if w["window_id"] == wid
                ),
                None,
            )
        query = self.query_one(Input).value.casefold()
        self.rows = self.nodes(query)
        self.filter_query = query
        self.revision += 1
        listing = self.query_one(ListView)
        await listing.clear()
        await listing.extend(
            ListItem(SwitchRow(row, row["key"] in self.expanded)) for row in self.rows
        )
        if self.rows:
            candidates = [previous] if previous else []
            while candidates and ":" in candidates[-1]:
                candidates.append(candidates[-1].rsplit(":", 1)[0])
            listing.index = next(
                (
                    i
                    for key in candidates
                    for i, row in enumerate(self.rows)
                    if row["key"] == key
                ),
                0,
            )
            self.pending = self.rows[listing.index]["window_id"]
        else:
            self.pending = None
            self.query_one(LayoutPreview).panes = []
            self.query_one(LayoutPreview).refresh()

    def selected(self):
        index = self.query_one(ListView).index
        return (
            self.rows[index]
            if index is not None and 0 <= index < len(self.rows)
            else None
        )

    def on_input_changed(self, event):
        pass

    def on_list_view_highlighted(self, event):
        row = self.selected()
        self.pending = row["window_id"] if row else None
        for widget in self.query(SwitchRow):
            widget.refresh()

    async def refresh_inventory(self):
        if self.refreshing or self.app.screen is not self:
            return
        self.refreshing = True
        try:
            await self.reload()
        except (OSError, RuntimeError, ValueError) as error:
            await self.error(error)
        finally:
            self.refreshing = False

    async def refresh_preview(self):
        if self.query_one(Input).value.casefold() != self.filter_query:
            await self.populate()
        if self.preview_busy or self.pending is None or self.app.screen is not self:
            return
        self.preview_busy = True
        target = self.pending
        revision = self.revision
        try:
            panes = await self.app.backend.snapshot(target)
            if self.pending == target and self.revision == revision and self.is_mounted:
                preview = self.query_one(LayoutPreview)
                if preview.panes != panes:
                    preview.panes = panes
                    preview.refresh()
        except (OSError, RuntimeError, ValueError) as error:
            await self.error(error)
        finally:
            self.preview_busy = False

    async def fold(self, expand=None):
        row = self.selected()
        if not row or row["kind"] == "pane":
            return
        key = row["key"]
        opened = key in self.expanded
        if expand is None:
            expand = not opened
        if expand:
            self.expanded.add(key)
        else:
            self.expanded.discard(key)
        await self.populate()

    async def on_key(self, event: events.Key):
        if event.key in ("up", "down"):
            listing = self.query_one(ListView)
            if self.rows:
                listing.index = max(
                    0,
                    min(
                        len(self.rows) - 1,
                        (listing.index or 0) + (1 if event.key == "down" else -1),
                    ),
                )
        elif event.key in ("left", "right"):
            await self.fold(event.key == "right")
        elif event.key == "ctrl+n":
            await self.action_new()
        elif event.key == "ctrl+r":
            await self.action_rename()
        elif event.key == "ctrl+o":
            self.action_more()
        else:
            return
        event.stop()
        event.prevent_default()

    async def on_input_submitted(self, event):
        await self.confirm()

    async def on_list_view_selected(self, event):
        await self.confirm()

    async def confirm(self, row=None):
        await self.inventory_ready.wait()
        query = self.query_one(Input).value.casefold()
        matches = self.nodes(query)
        selected = row or self.selected()
        if not row:
            selected = next(
                (r for r in matches if selected and r["key"] == selected["key"]),
                matches[0] if matches else None,
            )
        if not selected:
            return
        try:
            await targets.select(self.app.backend, selected)
            self.finished = True
            self.dismiss(None)
        except (OSError, RuntimeError, ValueError) as error:
            await self.error(error)
            await self.reload()

    async def action_new(self):
        def created(window):
            if window and self.is_mounted:
                self.finished = True
                self.dismiss(None)

        self.app.push_screen(NewSession(), created)

    async def action_rename(self):
        row = self.selected()
        if not row:
            return
        from cosmos_tui.ui.text_prompt import TextPrompt as FilePrompt

        async def submit(name, _):
            try:
                await targets.rename(self.app.backend, row, name)
                await self.reload()
            except (OSError, RuntimeError, ValueError) as error:
                await self.error(error)

        name = (
            row["session"]
            if row["kind"] == "session"
            else row["name"]
            if row["kind"] == "window"
            else row.get("pane_name", "")
        )
        self.app.push_screen(FilePrompt("Rename " + row["kind"], submit, initial=name))

    def action_more(self):
        row = self.selected()
        if not row:
            return
        choices = [("new", "New window")]
        if row["kind"] != "session":
            choices.extend(
                [
                    ("horizontal", "Split left / right"),
                    ("vertical", "Split top / bottom"),
                ]
            )
        choices.append(("refresh", "Refresh"))

        async def run(value):
            try:
                if value == "new":
                    await targets.new_window(self.app.backend, row)
                elif value in ("horizontal", "vertical"):
                    await targets.split(self.app.backend, row, value == "horizontal")
                if value:
                    await self.reload()
            except (OSError, RuntimeError, ValueError) as error:
                await self.error(error)

        self.app.push_screen(
            CompactMenu("More · " + row[row["kind"] + "_id"], choices),
            lambda value: self.app.run_worker(run(value)),
        )

    async def on_switch_row_action(self, event):
        event.stop()
        index = next(
            (i for i, row in enumerate(self.rows) if row["key"] == event.row["key"]),
            None,
        )
        if index is None:
            return
        self.query_one(ListView).index = index
        if event.action == "fold":
            await self.fold()
        elif event.action == "rename":
            await self.action_rename()
        else:
            self.action_more()

    async def on_layout_preview_chosen(self, event):
        row = self.selected()
        if row:
            await self.confirm(dict(row, kind="pane", pane_id=event.pane))

    async def on_click(self, event):
        if event.widget.id == "switch-new":
            event.stop()
            await self.action_new()

    def on_unmount(self):
        self.finished = True

    def action_cancel(self):
        self.finished = True
        self.dismiss(None)
