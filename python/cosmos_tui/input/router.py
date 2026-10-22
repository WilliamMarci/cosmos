from __future__ import annotations

import logging

from textual import events
from textual.widgets import Input

from cosmos_tui.core import rpc
from cosmos_tui.core.controller import Controller
from cosmos_tui.features.assistant.presenter import Assistant
from cosmos_tui.features.navigation.about import About
from cosmos_tui.features.navigation.menus import ActionDrawer, StartMenu
from cosmos_tui.features.navigation.switcher import Switcher
from cosmos_tui.features.search.bar import BottomSearch
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.input import keymap
from cosmos_tui.input.shortcuts import MODIFIER_KEYS, leader_key
from cosmos_tui.ui.help import Help
from cosmos_tui.ui.menus import CompactMenu


class InputRouter(Controller):
    async def on_event(self, event):
        app = self.app
        # Resolve Leader before forwarding to focused widgets. Keyboard protocols
        # may describe shifted punctuation by character rather than binding name.
        if isinstance(event, events.Key) and not event.is_forwarded:
            if event.key in MODIFIER_KEYS:
                return
            command = keymap.resolve(
                "global", leader_key(event.key, event.character), app.settings
            )
            if command:
                if command.target == "actions":
                    app.action_context_actions()
                elif command.target == "start":
                    app.action_start_menu()
                elif command.target in ("ime_enable", "ime_disable"):
                    await app.action_leader_key(command.target)
                elif command.target == "ime_toggle":
                    await app.ime.toggle()
                elif command.target == "ime_width":
                    await app.ime.toggle_width()
                return
            leader = "ctrl+a" if app.settings["leader"] == "C-a" else "ctrl+b"
            if event.key == leader:
                await self.action_leader(leader)
                return
            if app.prefix:
                key = leader_key(event.key, event.character)
                context = self.key_context()
                command = keymap.resolve(context, "leader+" + key, app.settings)
                if command:
                    if command.context.startswith("assistant") and isinstance(
                        app.screen, Assistant
                    ):
                        app.prefix = False
                        await app.screen.run_action(command.target)
                    else:
                        await app.action_leader_key(command.target)
                else:
                    app.prefix = False
                    logging.getLogger(__name__).debug(
                        "unmapped Leader key %s", event.key
                    )
                return
        if isinstance(event, events.Key) and not event.is_forwarded:
            if await app.ime.handle(event):
                return
            context = self.key_context()
            if context != "workspace" and not (
                context == "viewer" and app.search is not None
            ):
                key = leader_key(event.key, event.character)
                command = keymap.resolve(context, key, app.settings)
                if context == "copy":
                    if command:
                        await app.copy_action(command.target)
                    return
                if command and (
                    command.context.startswith("assistant")
                    or context == "content_search"
                ):
                    await app.screen.run_action(command.target)
                    return
                if command:
                    canonical = command.target
                    character = canonical if len(canonical) == 1 else None
                    event = events.Key(canonical, character)
                elif keymap.default_reserved(context, key):
                    return
        if (
            isinstance(event, events.Key)
            and not event.is_forwarded
            and isinstance(app.screen, Switcher)
        ):
            app.screen.set_focus(app.screen.query_one(Input))
        await app._dispatch_native(event)

    def key_context(self):
        app = self.app
        if not app._screen_stack:
            return "workspace"
        if isinstance(app.screen, Assistant):
            return "assistant_actions" if app.screen.actions_mode else "assistant"
        if isinstance(app.screen, KeyBindingEditor):
            return "key_settings"
        if isinstance(app.screen, Switcher):
            return "switch"
        if isinstance(app.screen, ThemePanel):
            return "theme_settings"
        if isinstance(app.screen, Palette):
            return "palette"
        if isinstance(app.screen, CompactMenu):
            return "menu"
        if isinstance(app.screen, Help):
            return "help"
        if isinstance(app.screen, About):
            return "about"
        if isinstance(app.screen, BottomSearch):
            return "content_search"
        if isinstance(app.screen, ActionDrawer):
            return "action_drawer"
        if isinstance(app.screen, StartMenu):
            return "start_menu"
        if app.view_focus is not None:
            return "surface"
        pane = app.active()
        if pane and pane.copy_mode and not pane.viewer:
            return "copy"
        return (
            ("viewer_search" if app.search is not None else "viewer")
            if pane and pane.viewer
            else "workspace"
        )

    def check_action(self, action, parameters):
        app = self.app
        if action == "leader_key":
            return app.prefix
        if action == "leader":
            return parameters[0] == (
                "ctrl+a" if app.settings["leader"] == "C-a" else "ctrl+b"
            )
        return True

    async def action_leader(self, key):
        app = self.app
        logging.getLogger(__name__).debug("action_leader %s", key)
        if app.prefix:
            app.prefix = False
            await app.backend.send(key)
        else:
            app.prefix = True

    async def on_key(self, event: events.Key):
        app = self.app
        if app.screen is not app._workspace_screen:
            return
        event.stop()
        event.prevent_default()
        if app.prefix:
            app.prefix = False
            if event.key == "escape":
                return
        pane = app.active()
        if (
            event.key == "enter"
            and pane
            and app.assistant_ui.passive
            and app.assistant_ui.passive["pane"] == pane.id
        ):
            app.assistant_ui.passive = None
        if app.view_focus is not None:
            if event.key == "escape":
                await rpc.call(
                    "presentation.close",
                    {"client": app.client, "view": app.view_focus},
                )
            else:
                named = {
                    "enter": "enter",
                    "backspace": "backspace",
                    "up": "up",
                    "down": "down",
                    "left": "left",
                    "right": "right",
                    "home": "home",
                    "end": "end",
                    "pageup": "page_up",
                    "pagedown": "page_down",
                }
                if event.character and event.character.isprintable():
                    key = {"type": "char", "value": event.character}
                elif event.key.startswith("ctrl+") and len(event.key) == 6:
                    key = {"type": "ctrl", "value": ord(event.key[-1]) - 96}
                else:
                    key = {"type": named.get(event.key, "escape")}
                await rpc.call("input.send", {"client": app.client, "key": key})
            return
        if pane and pane.viewer:
            await app.reader_ui.on_key(event, pane)
        else:
            await app.backend.send(event.key, event.character)

    async def on_paste(self, event: events.Paste):
        app = self.app
        if app.screen is app._workspace_screen:
            event.stop()
            if app.search is not None:
                app.search = (app.search + event.text)[:8192]
            elif not (app.active() and app.active().viewer):
                await app.backend.paste(event.text)
