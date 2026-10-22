from __future__ import annotations

import base64
import json
from pathlib import Path

from textual import events

from cosmos_tui.core import rpc
from cosmos_tui.core.controller import Controller
from cosmos_tui.features.assistant.presenter import Assistant
from cosmos_tui.features.navigation.about import About
from cosmos_tui.features.navigation.menus import ActionDrawer, StartMenu, mod_entries
from cosmos_tui.features.search.bar import BottomSearch
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.input import keymap


class NavigationController(Controller):
    def action_context_actions(self):
        app = self.app
        if isinstance(app.screen, ActionDrawer):
            app.screen.dismiss(None)
            return
        source, context, pane = app.screen, app.key_context(), app.active()
        bounds = (pane.x, pane.y, pane.width, pane.height) if pane else None

        async def load():
            snapshot = await rpc.call("state.snapshot")
            selected = [c for c in keymap.COMMANDS if c.context == context]
            if isinstance(source, BottomSearch) and not source.steps:
                selected = [c for c in selected if c.target not in ("next", "previous")]
            if (
                pane
                and pane.viewer
                and Path(
                    json.loads(base64.b64decode(pane.viewer))["path"]
                ).suffix.lower()
                != ".pdf"
            ):
                selected = [c for c in selected if c.id != "viewer.search"]
            if source is app._workspace_screen and pane:
                available = {
                    "switch",
                    "detach",
                    "split_horizontal",
                    "split_vertical",
                    "next_pane",
                    "zoom",
                    "agent",
                }
                available.update("focus_" + d for d in ("left", "down", "up", "right"))
                available.update("resize_" + d for d in ("left", "down", "up", "right"))
                if not pane.viewer and not pane.copy_mode:
                    available.update(("copy_mode", "history_search", "paste_buffer"))
                    program = await app.backend.request(
                        f"display-message -p -t {pane.id} '#{{pane_current_command}}'"
                    )
                    if program == ["bash"]:
                        available.add("assistant")
                selected = [c for c in selected if c.context != "workspace"]
                selected += [
                    c
                    for c in keymap.COMMANDS
                    if c.id in {"workspace." + name for name in available}
                ]
            if isinstance(source, Assistant) and source.controller.busy:
                selected = [
                    c
                    for c in selected
                    if c.target in ("cancel", "actions", "cycle(-1)", "cycle(1)")
                ]
            rows = [
                dict(
                    id=c.id,
                    label=c.label,
                    kind="command",
                    command=c,
                    group="Cosmos / " + c.context,
                    shortcut=next(
                        (
                            keys
                            for keys, label in keymap.help_rows(c.context, app.settings)
                            if label == c.label
                        ),
                        "",
                    ),
                )
                for c in selected
            ]
            return rows + mod_entries(snapshot, "actions", context)

        async def choose(row):
            if row and app.screen is source:
                if app.key_context() != context or (
                    pane and (not app.active() or app.active().id != pane.id)
                ):
                    await app.action_error(
                        "context action", "Source context changed; reopen Actions"
                    )
                    return
                await self.invoke_entry(row, source)

        app.push_screen(ActionDrawer(load, bounds), choose)

    def action_start_menu(self):
        app = self.app
        if isinstance(app.screen, StartMenu):
            app.screen.dismiss(None)
            return
        context = app.key_context()

        async def load():
            snapshot = await rpc.call("state.snapshot")
            rows = [
                dict(label="Settings", kind="settings", group="Cosmos"),
                dict(label="About", kind="about", group="Cosmos"),
                dict(
                    label="Notifications",
                    kind="settings",
                    menu="notifications",
                    group="Cosmos",
                ),
            ]
            for command in keymap.COMMANDS:
                if command.id in ("workspace.switch", "workspace.agent"):
                    rows.append(
                        dict(
                            id=command.id,
                            label=command.label,
                            kind="command",
                            command=command,
                            group="Cosmos",
                        )
                    )
            return rows + mod_entries(snapshot, "start", context)

        async def choose(row):
            if row:
                while (
                    app.screen is not app._workspace_screen
                    and len(app._screen_stack) > 1
                ):
                    await app.pop_screen()
                await self.invoke_entry(row, app.screen)

        app.push_screen(StartMenu(load), choose)

    async def invoke_entry(self, row, source):
        app = self.app
        try:
            if row["kind"] == "settings":
                app.push_screen(Palette(row.get("menu", "settings")))
            elif row["kind"] == "about":
                app.push_screen(About())
            elif row["kind"] == "mod":
                await rpc.call(
                    "actions.invoke",
                    {"id": row["id"], "params": {"client": app.client}},
                )
            elif row["kind"] == "command":
                command = row["command"]
                if command.context == "workspace":
                    await app.action_leader_key(command.target)
                elif command.context == "copy":
                    await app.copy_action(command.target)
                elif (
                    command.context.startswith("assistant")
                    or command.context == "content_search"
                ):
                    await source.run_action(command.target)
                else:
                    app.post_message(
                        events.Key(
                            command.target,
                            command.target if len(command.target) == 1 else None,
                        )
                    )
        except (OSError, RuntimeError) as error:
            await app.action_error("menu action", error)
