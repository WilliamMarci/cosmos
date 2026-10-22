from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input, Label, ListItem, ListView, Static

from cosmos_tui.core import rpc
from cosmos_tui.features.navigation.about import About
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.input import keymap
from cosmos_tui.input.groups import GROUPS, group
from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.zones import Zone
from cosmos_tui.ui.keyboard import KeyboardPreview, key_legend


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
            listing = ListView(id="actions")
            listing.styles.margin = 0
            yield listing
            legend = Static(key_legend(self.app.role_colors), id="binding-legend")
            legend.styles.height = 1
            yield legend
            yield KeyboardPreview(id="binding-keyboard")
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
        if self.menu == "keys" and not query:
            rows = [
                dict(label=name, kind="menu", menu="keys:" + name) for name in GROUPS
            ]
        elif self.menu == "keys" or self.menu.startswith("keys:"):
            settings = snapshot.get("settings", getattr(self.app, "settings", {}))
            rows = [
                dict(
                    label=f"{command.label}  {', '.join(keymap.bindings(command, settings))}",
                    kind="keybinding",
                    command=command,
                )
                for command in keymap.COMMANDS
                if self.menu == "keys" or group(command) == self.menu[5:]
            ]
        if self.menu == "keys:General & menus" or (self.menu == "keys" and query):
            rows = [
                a
                for a in actions
                if a.get("category") == "keys" and a.get("kind") == "setting"
            ] + rows
        if self.menu == "ime_settings":
            current = snapshot.get("settings", {}).get("ime_number_style", "normal")
            rows = [
                dict(
                    label=f"Candidate numbers: {sample}"
                    + (" · current" if style == current else ""),
                    kind="ime_style",
                    style=style,
                )
                for style, sample in [
                    ("superscript", "¹ ² ³"),
                    ("subscript", "₁ ₂ ₃"),
                    ("normal", "1 2 3"),
                ]
            ]
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
            rows.append(dict(label="Theme", kind="theme"))
            rows.append(dict(label="Input method", kind="menu", menu="ime_settings"))
            rows.append(dict(label="About", kind="about"))
        self.rows = [a for a in rows if query in a["label"].casefold()]
        listing = self.query_one(ListView)
        await listing.clear()
        await listing.extend(ListItem(Label(row["label"])) for row in self.rows)
        if self.rows:
            listing.index = 0
        self.update_keyboard()
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
        if row["kind"] == "theme":
            self.app.push_screen(ThemePanel())
            return
        if row["kind"] == "ime_style":
            settings = await rpc.call("settings.get")
            settings["ime_number_style"] = row["style"]
            try:
                await rpc.call("settings.replace", settings)
                self.app.settings = settings
                await self.populate()
            except RuntimeError as error:
                await self.app.action_error("input method settings", error)
            return
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

    def update_keyboard(self):
        keyboard = self.query_one(KeyboardPreview)
        keyboard.fit(minimum_height=32)
        keyboard.display = keyboard.display and self.menu.startswith("keys:")
        self.query_one("#binding-legend").display = keyboard.display
        index = self.query_one(ListView).index
        command = (
            self.rows[index].get("command")
            if index is not None and index < len(self.rows)
            else None
        )
        keyboard.present(keymap.bindings(command, self.app.settings) if command else [])

    def on_list_view_highlighted(self, event):
        if self.is_mounted:
            self.update_keyboard()

    def on_resize(self):
        if self.is_mounted:
            self.update_keyboard()
