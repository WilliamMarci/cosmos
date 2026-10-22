from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input, ListItem, ListView, Static

from cosmos_tui.core import rpc
from cosmos_tui.features.navigation.about import About
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.input import keymap
from cosmos_tui.input.groups import GROUPS, group
from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.settings import SettingRow
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
                    label=command.label,
                    hint=" / ".join(
                        keymap.display_binding(k, settings)
                        for k in keymap.bindings(command, settings)
                    ),
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
        settings = snapshot.get("settings", {})

        def choice(label, key, values, default, *, local=False):
            current = self.app.mouse_mode if local else settings.get(key, default)
            values = list(values)
            if current not in [value for value, _ in values]:
                values.append((current, str(current)))
            return dict(
                label=label,
                kind="choice",
                key=key,
                choices=values,
                value=current,
                local=local,
            )

        if self.menu == "reader_settings":
            rows = [
                choice(
                    "Cache size",
                    "viewer_cache_mb",
                    [(n, f"{n} MiB") for n in (64, 128, 256, 512)],
                    128,
                ),
                choice(
                    "Maximum image size",
                    "viewer_image_max_mb",
                    [(n, f"{n} MiB") for n in (16, 32, 64, 128, 256, 512, 1024)],
                    32,
                ),
                choice(
                    "Prefetch adjacent pages",
                    "viewer_prefetch",
                    [(False, "Off"), (True, "On")],
                    True,
                ),
                dict(label="Clear this client's reader cache", kind="reader_clear"),
            ]
        if self.menu == "status_settings":
            rows = [
                choice(
                    "Path depth",
                    "status_path_depth",
                    [(0, "All")] + [(n, str(n)) for n in (1, 2, 3, 4, 5, 8)],
                    3,
                ),
                choice(
                    "Path maximum length",
                    "status_path_max_length",
                    [(n, str(n)) for n in (20, 30, 40, 60, 80, 120)],
                    40,
                ),
                choice(
                    "Path alignment",
                    "status_path_align",
                    [(v, v.title()) for v in ("left", "center", "right")],
                    "right",
                ),
                choice(
                    "Block separator",
                    "status_separator",
                    [
                        (v, v.title())
                        for v in ("powerline", "capsule", "slash", "vertical", "none")
                    ],
                    "powerline",
                ),
            ]
        if self.menu == "input_settings":
            rows = [
                dict(label="Mouse mode", kind="menu", menu="mouse_settings"),
                dict(label="Input method", kind="menu", menu="ime_settings"),
            ]
        if self.menu == "mouse_settings":
            rows = [
                choice(
                    "Mouse mode",
                    "mouse_mode",
                    [(m, m.title()) for m in ("auto", "cell", "pixel")],
                    "auto",
                    local=True,
                )
            ]
        if self.menu == "ime_settings":
            rows = [
                choice(
                    "Candidate numbers",
                    "ime_number_style",
                    [
                        ("normal", "1 2 3"),
                        ("superscript", "¹ ² ³"),
                        ("subscript", "₁ ₂ ₃"),
                    ],
                    "normal",
                )
            ]
        for index, row in enumerate(rows):
            if row.get("kind") == "setting":
                key = row.get("key")
                options = {
                    "leader": (
                        "Leader key",
                        [("C-b", "Ctrl+B"), ("C-a", "Ctrl+A")],
                        "C-b",
                    ),
                    "theme": (
                        "Interface theme",
                        [("dark", "Dark"), ("light", "Light")],
                        "dark",
                    ),
                    "status_visible": (
                        "Status bar",
                        [(False, "Hidden"), (True, "Visible")],
                        True,
                    ),
                    "reduced_motion": (
                        "Reduced motion",
                        [(False, "Off"), (True, "On")],
                        False,
                    ),
                    "notifications_enabled": (
                        "Notifications",
                        [(False, "Off"), (True, "On")],
                        True,
                    ),
                }
                if key in options:
                    label, values, default = options[key]
                    rows[index] = choice(label, key, values, default)
        if self.menu == "keys:General & menus" or (self.menu == "keys" and query):
            rows += [
                choice(
                    name.title(),
                    name,
                    [("off", "Off")]
                    + [
                        ("C-" + ch, "Ctrl+" + ch.upper())
                        for ch in "abcdefghijklmnopqrstuvwxyz"
                    ],
                    default,
                )
                for name, default in (("leader2", "C-a"), ("leader3", "C-m"))
            ]
        if self.menu == "notifications":
            rows.append(
                choice(
                    "Default timeout",
                    "notification_timeout_ms",
                    [
                        (n, f"{n // 1000}s")
                        for n in (1000, 3000, 5000, 10000, 30000, 60000)
                    ],
                    5000,
                )
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
            rows.append(dict(label="Theme", kind="theme"))
            rows.append(dict(label="Reader", kind="menu", menu="reader_settings"))
            rows.append(dict(label="Status bar", kind="menu", menu="status_settings"))
            rows.append(dict(label="Input", kind="menu", menu="input_settings"))
            rows.append(dict(label="About", kind="about"))
        self.rows = [a for a in rows if query in a["label"].casefold()]
        listing = self.query_one(ListView)
        selected = listing.index
        await listing.clear()
        await listing.extend(ListItem(SettingRow(row)) for row in self.rows)
        if self.rows:
            listing.index = min(selected or 0, len(self.rows) - 1)
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
        if row["kind"] == "choice":
            await self.cycle_choice(row, 1)
            return
        if row["kind"] == "reader_clear":
            self.app.reader_ui.clear_cache()
            return
        if row["kind"] == "theme":
            self.app.push_screen(ThemePanel())
            return
        if row["kind"] == "keybinding":
            self.app.push_screen(
                KeyBindingEditor(row["command"]),
                lambda saved: self.call_later(self.populate) if saved else None,
            )
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
            self.query_one(ListView).index = 0
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
            await self.app.action_error("settings.action", error)

    async def cycle_choice(self, row, direction):
        values = [value for value, _ in row["choices"]]
        value = values[(values.index(row["value"]) + direction) % len(values)]
        try:
            if row.get("local"):
                self.app.set_mouse_mode(value)
            else:
                settings = await rpc.call("settings.get")
                settings[row["key"]] = value
                keymap.validate(settings.get("keybindings", {}), settings)
                await rpc.call("settings.replace", settings)
                actual = await rpc.call("settings.get")
                if actual.get(row["key"]) != value:
                    raise RuntimeError(
                        "Coordinator did not retain this setting; update/restart the coordinator and retry"
                    )
                self.app.settings = actual
            await self.populate()
        except (RuntimeError, OSError, ValueError) as failure:
            await self.app.action_error("settings." + row["key"], failure)

    async def on_setting_row_cycle(self, event):
        event.stop()
        await self.cycle_choice(event.row, event.direction)

    async def action_cycle_previous(self):
        await self.cycle_selected(-1)

    async def action_cycle_next(self):
        await self.cycle_selected(1)

    async def cycle_selected(self, direction):
        index = self.query_one(ListView).index
        if (
            index is not None
            and index < len(self.rows)
            and self.rows[index].get("choices")
        ):
            await self.cycle_choice(self.rows[index], direction)

    async def action_parent(self):
        await self.action_back()

    async def action_child(self):
        index = self.query_one(ListView).index
        if (
            index is not None
            and index < len(self.rows)
            and self.rows[index]["kind"] in ("menu", "theme", "about", "keybinding")
        ):
            await self.invoke()

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
