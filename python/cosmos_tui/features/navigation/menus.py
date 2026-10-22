"""Context actions and grouped application launchers; no terminal resizing."""

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Label, ListItem, ListView, Static

from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import BottomSheet, Frame, SheetShadow
from cosmos_tui.ui.zones import Zone
from cosmos_tui.ui.cells import cell_width


class StatusBar(Static):
    start_width = 8

    def on_click(self, event):
        if event.x < self.start_width:
            event.stop()
            self.app.action_start_menu()
        elif hasattr(self.app, "ime"):
            start = self.size.width - cell_width(" " + self.app.ime.status() + " ")
            if event.x >= start:
                event.stop()
                action = (
                    self.app.ime.toggle
                    if event.x < start + 4
                    else self.app.ime.toggle_width
                )
                self.app.run_worker(action())


class EntryPicker(CosmosModal):
    zone = Zone.POP_WINDOW
    BINDINGS = [Binding("escape", "cancel", show=False)]
    DEFAULT_CSS = """
    EntryPicker { background: transparent; background-tint: transparent; }
    #entry-frame { position: absolute; padding: 0 1; }
    #entry-filter { height: 1; border: none; padding: 0; }
    #entry-list { height: 1fr; margin-top: 0; }
    """

    def __init__(self, loader, bounds=None):
        super().__init__()
        self.styles.background = "transparent"
        self.styles.background_tint = "transparent"
        self.loader, self.bounds = loader, bounds
        self.entries, self.rows = [], []
        self.ready = False
        self.screen_size = None

    def compose(self):
        yield SheetShadow(id="entry-shadow")
        with BottomSheet(id="entry-frame") as frame:
            frame.set_heading(
                "Actions" if isinstance(self, ActionDrawer) else "Cosmos",
                "global.actions" if isinstance(self, ActionDrawer) else "global.start",
            )
            listing = ListView(id="entry-list")
            listing.styles.margin = 0
            yield listing
            yield CosmosInput(
                placeholder="Filter actions"
                if isinstance(self, ActionDrawer)
                else "Find an entry",
                id="entry-filter",
            )

    async def on_mount(self):
        self.screen_size = self.app.size
        try:
            self.entries = await self.loader()
        except (OSError, RuntimeError) as error:
            self.entries = [dict(label=str(error), enabled=False)]
        self.ready = True
        await self.populate()
        self.query_one(CosmosInput).focus()

    def place(self):
        bar = self.app.query_one("#status", Static)
        bottom = self.app.size.height - int(bar.display)
        if isinstance(self, ActionDrawer):
            x, y, width, height = self.bounds or (0, 0, self.app.size.width, bottom)
            width = max(1, min(width, self.app.size.width - x))
            height = max(1, min(height, bottom - y))
            rows = min(height, max(3, height // 2))
            offset = x, y + height - rows
        else:
            width = min(44, self.app.size.width)
            rows = max(1, min(bottom, max(6, min(len(self.rows) + 3, 20))))
            offset = 0, bottom - rows
        frame = self.query_one(Frame)
        self.query_one(SheetShadow).place(frame, *offset, width, rows)

    async def populate(self):
        query = self.query_one(CosmosInput).value.casefold()
        filtered = [
            e
            for e in self.entries
            if query in (e.get("group", "") + " " + e["label"]).casefold()
        ]
        self.rows = []
        group = None
        for entry in sorted(filtered, key=lambda e: e.get("group", "")):
            heading = entry.get("group", "")
            if heading and heading != group:
                self.rows.append(dict(label=heading, enabled=False, heading=True))
                group = heading
            self.rows.append(entry)
        listing = self.query_one(ListView)
        await listing.clear()
        palette = getattr(self.app, "role_colors", {})
        items = []
        for row in self.rows:
            text = Text(row["label"])
            if row.get("heading"):
                text.stylize("bold " + palette.get("accl", "#a0cdfa"))
            elif row.get("shortcut"):
                text.append(
                    "  " + row["shortcut"], style=palette.get("mute", "#7a8092")
                )
            items.append(ListItem(Label(text), disabled=not row.get("enabled", True)))
        await listing.extend(items)
        listing.index = next(
            (i for i, row in enumerate(self.rows) if row.get("enabled", True)), None
        )
        self.place()

    async def on_input_changed(self, event):
        if self.ready:
            await self.populate()

    def on_key(self, event):
        if event.key in ("up", "down"):
            listing = self.query_one(ListView)
            indices = [i for i, row in enumerate(self.rows) if row.get("enabled", True)]
            if indices:
                old = indices.index(listing.index) if listing.index in indices else 0
                listing.index = indices[
                    max(
                        0,
                        min(len(indices) - 1, old + (1 if event.key == "down" else -1)),
                    )
                ]
            event.stop()
            event.prevent_default()

    def choose(self):
        index = self.query_one(ListView).index
        if (
            index is not None
            and index < len(self.rows)
            and self.rows[index].get("enabled", True)
        ):
            self.dismiss(self.rows[index])

    def on_input_submitted(self, event):
        self.choose()

    def on_list_view_selected(self, event):
        self.choose()

    def action_cancel(self):
        self.dismiss(None)

    def on_resize(self, event):
        if self.ready and self.screen_size != self.app.size:
            # The captured source rectangle is invalid after a resize. Reopen
            # against the newly measured pane instead of covering another pane.
            if isinstance(self, ActionDrawer):
                self.dismiss(None)
            else:
                self.screen_size = self.app.size
                self.place()


class ActionDrawer(EntryPicker):
    pass


class StartMenu(EntryPicker):
    pass


def mod_entries(snapshot, surface, context):
    """Manifest registration -> visible entry; contexts are UI scope, not sandboxing."""
    active = {
        m["id"]
        for m in snapshot.get("mods", [])
        if m["status"]["state"]
        in ("ready", "starting", "running", "backoff", "stopping")
    }
    return [
        dict(row, group="Mods / " + (row.get("group") or row["mod"]))
        for row in snapshot.get("actions", [])
        if row.get("kind") == "mod"
        and surface in row.get("surfaces", ["start", "actions"])
        and (
            surface == "start"
            or context in row.get("contexts", ["workspace"])
            or "*" in row.get("contexts", [])
        )
        and row.get("enabled", row["mod"] not in active)
        and row["mod"] not in active
    ]
