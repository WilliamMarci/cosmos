from __future__ import annotations

import asyncio

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
            selected = [
                c
                for c in keymap.COMMANDS
                if c.context == context or c.id.startswith("global.ime_")
            ]
            if isinstance(source, BottomSearch) and not source.steps:
                selected = [c for c in selected if c.target not in ("next", "previous")]
            if (
                pane
                and pane.viewer
                and Path(
                    json.loads(base64.b64decode(pane.viewer))["path"]
                ).suffix.lower()
                not in {".pdf", ".epub", ".md", ".markdown", ".html", ".htm"}
            ):
                selected = [c for c in selected if c.id != "viewer.search"]
            if source is app._workspace_screen and pane:
                available = {
                    "switch",
                    "files",
                    "detach",
                    "quit",
                    "ime_toggle",
                    "ime_width",
                    "new_session",
                    "split_horizontal",
                    "split_vertical",
                    "next_pane",
                    "identify_panes",
                    "zoom",
                    "agent",
                    "mouse_passthrough",
                    "private_pane",
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
            if pane and pane.viewer:
                from cosmos_tui.features.reader.preferences import commands

                selected = await asyncio.to_thread(
                    commands, app.reader_ui, pane, selected
                )
            passthrough = "On" if app.settings.get("mouse_passthrough", True) else "Off"
            from cosmos_tui.features.files.actions import command_group

            rows = [
                dict(
                    id=c.id,
                    label=c.label
                    + (" · " + passthrough if c.target == "mouse_passthrough" else ""),
                    kind="command",
                    command=c,
                    group=command_group(c)
                    if c.context == "files"
                    else "Cosmos / " + c.context,
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
                if command.id in (
                    "workspace.switch",
                    "workspace.files",
                    "workspace.agent",
                    "workspace.new_session",
                    "workspace.quit",
                ):
                    rows.append(
                        dict(
                            id=command.id,
                            label="Files"
                            if command.id == "workspace.files"
                            else command.label,
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

    async def open_files(self):
        app = self.app
        pane = app.active()
        if not pane:
            raise RuntimeError("No active pane")
        if pane.viewer:
            state = app.reader_ui.state(pane)
            if state.get("kind") == "files":
                return
            path = str(Path(state["path"]).parent)
        else:
            rows = await app.backend.request(
                f"display-message -p -t {pane.id} '#{{pane_current_path}}'"
            )
            path = "\n".join(rows)
        if not path or not Path(path).is_dir():
            raise ValueError("Current directory is unavailable")
        await app.reader_ui.update_viewer(pane, dict(kind="files", path=path, cursor=0))

    async def invoke_entry(self, row, source):
        try:
            await self.execute_entry(row, source)
        except (OSError, RuntimeError) as error:
            await self.app.action_error("menu action", error)

    async def execute_entry(self, row, source):
        app = self.app
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
            if command.id == "global.actions":
                app.action_context_actions()
            elif command.id == "global.start":
                app.action_start_menu()
            elif command.id == "global.keyboard_passthrough":
                app.inputs.toggle_passthrough()
            elif command.context == "workspace" or command.id.startswith("global.ime_"):
                await app.action_leader_key(command.target)
            elif command.context == "copy":
                await app.copy_action(command.target)
            elif (
                command.context.startswith("assistant")
                or command.context == "content_search"
                or (
                    command.context == "palette"
                    and command.target
                    in ("cycle_previous", "cycle_next", "parent", "child")
                )
            ):
                await source.run_action(command.target)
            else:
                app.post_message(
                    events.Key(
                        command.target,
                        command.target if len(command.target) == 1 else None,
                    )
                )
