from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input, Label, ListItem, ListView

from cosmos_tui.core import rpc
from cosmos_tui.features.navigation.about import About
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.input import keymap
from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.zones import Zone


class Palette(CosmosModal):
    zone = Zone.POP_WINDOW
    BINDINGS = [Binding("escape", "back", show=False)]

    def __init__(self, menu="settings"):
        super().__init__()
        self.menu = menu
        self.stack = []
        self.rows = []

    def compose(self):
        with Frame(id="palette") as frame:
            frame.set_heading("Cosmos / settings", "workspace.palette")
            yield ListView(id="actions")
            yield CosmosInput(placeholder="", id="filter")

    async def on_mount(self):
        await self.populate()
        self.query_one(Input).focus()

    async def populate(self):
        query = self.query_one(Input).value.casefold()
        snapshot = await rpc.call("state.snapshot")
        actions = snapshot["actions"]
        rows = [
            a
            for a in actions
            if a.get("category") == self.menu
            and a.get("id") not in {"objects.list", "settings.apply", "keys.apply"}
            and a.get("kind") != "mod"
        ]
        if self.menu == "keys":
            settings = snapshot.get("settings", getattr(self.app, "settings", {}))
            rows.extend(
                dict(
                    label=f"{command.context} · {command.label}  {', '.join(keymap.bindings(command, settings))}",
                    kind="keybinding",
                    command=command,
                )
                for command in keymap.COMMANDS
            )
        if self.menu == "mods":
            rows += [
                dict(
                    label=f"{m['id']} · {m['status']['state']}",
                    kind="rpc",
                    method="mods.stop"
                    if m["status"]["state"]
                    in ("ready", "starting", "running", "backoff")
                    else "mods.start",
                    params={"id": m["id"], "client": self.app.client},
                )
                for m in snapshot["mods"]
            ]
        if self.menu == "settings":
            rows.append(dict(label="About", kind="about"))
        self.rows = [a for a in rows if query in a["label"].casefold()]
        listing = self.query_one(ListView)
        await listing.clear()
        await listing.extend(ListItem(Label(row["label"])) for row in self.rows)
        if self.rows:
            listing.index = 0
        self.query_one("#palette", Frame).set_heading(
            "Cosmos / " + self.menu, "workspace.palette"
        )

    async def on_input_changed(self, event):
        await self.populate()

    async def on_input_submitted(self, event):
        await self.invoke()

    async def on_list_view_selected(self, event):
        await self.invoke()

    async def on_key(self, event):
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
            event.stop()
            event.prevent_default()

    async def invoke(self):
        index = self.query_one(ListView).index
        if index is None or index >= len(self.rows):
            return
        row = self.rows[index]
        if row["kind"] == "keybinding":
            self.app.push_screen(KeyBindingEditor(row["command"]))
            return
        if row["kind"] == "about":
            self.app.push_screen(About())
            return
        if row["kind"] == "local":
            self.dismiss()
            self.app.call_after_refresh(self.app.action_leader_key, row["key"])
            return
        if row["kind"] == "menu":
            self.stack.append(self.menu)
            self.menu = row["menu"]
            self.query_one(Input).value = ""
            await self.populate()
            return
        try:
            if row.get("method") in ("mods.start", "mods.stop"):
                await rpc.call(row["method"], row["params"])
            elif row.get("kind") == "rpc" and "id" not in row:
                await rpc.call(row["method"], row.get("params", {}))
            else:
                await rpc.call(
                    "actions.invoke",
                    {"id": row["id"], "params": {"client": self.app.client}},
                )
            await self.populate()
        except Exception as error:
            self.app.message = str(error)

    async def action_back(self):
        if self.stack:
            self.menu = self.stack.pop()
            self.query_one(Input).value = ""
            await self.populate()
        else:
            self.dismiss()
