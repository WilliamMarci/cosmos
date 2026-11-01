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
from cosmos_tui.features.reader.jump import PageJump
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.input import keymap
from cosmos_tui.input.shortcuts import MODIFIER_KEYS, leader_key
from cosmos_tui.ui.help import Help
from cosmos_tui.ui.menus import CompactMenu


class InputRouter(Controller):
    async def _terminal_input(self):
        """Only real keys delivered to a terminal count as human input."""
        from cosmos_tui.features.agent.control import human_input

        await human_input(self.app, self.app.active())

    def toggle_passthrough(self):
        self.keyboard_passthrough = not getattr(self, "keyboard_passthrough", False)
        self.passthrough_prefix = None
        self.app.prefix = False

    async def forward_passthrough(self, event):
        """Reserve only the configured escape chord; forward all other keys."""
        app = self.app
        if event.key in MODIFIER_KEYS:
            return
        key = leader_key(event.key, event.character)
        pending = getattr(self, "passthrough_prefix", None)
        if pending:
            self.passthrough_prefix = None
            chord, names = pending
            for name in names:
                command = keymap.resolve("global", name + "+" + key, app.settings)
                if command and command.target == "keyboard_passthrough":
                    self.toggle_passthrough()
                    return
            await self._terminal_input()
            await app.backend.send(chord)
            await app.backend.send(event.key, event.character)
            return
        command = keymap.resolve("global", key, app.settings)
        if command and command.target == "keyboard_passthrough":
            self.toggle_passthrough()
            return
        names = tuple(
            name
            for name, chord in keymap.active_leader_chords(app.settings).items()
            if chord == event.key
        )
        if names:
            self.passthrough_prefix = (event.key, names)
        else:
            await self._terminal_input()
            await app.backend.send(event.key, event.character)

    async def on_event(self, event):
        app = self.app
        if (
            isinstance(event, events.Key)
            and not event.is_forwarded
            and getattr(self, "keyboard_passthrough", False)
            and self.key_context() == "workspace"
        ):
            await self.forward_passthrough(event)
            return
        if isinstance(event, events.Key) and not event.is_forwarded:
            if await app.workspace.identify_key(event):
                return
        # Resolve Leader before forwarding to focused widgets. Keyboard protocols
        # may describe shifted punctuation by character rather than binding name.
        if isinstance(event, events.Key) and not event.is_forwarded:
            if event.key in MODIFIER_KEYS:
                return
            command = keymap.resolve(
                "global", leader_key(event.key, event.character), app.settings
            )
            if command:
                if command.target == "keyboard_passthrough":
                    self.toggle_passthrough()
                elif command.target == "actions":
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
            names = tuple(
                name
                for name, chord in keymap.active_leader_chords(app.settings).items()
                if event.key == chord
            )
            if names:
                await self.action_leader(event.key, names)
                return
            if not app.prefix and self.key_context() == "workspace":
                direct = keymap.resolve(
                    "workspace", leader_key(event.key, event.character), app.settings
                )
                if direct and direct.context == "workspace":
                    await app.action_leader_key(direct.target)
                    return
            if app.prefix:
                key = leader_key(event.key, event.character)
                context = self.key_context()
                command = next(
                    (
                        command
                        for name in getattr(app, "prefix_names", ("leader",))
                        if (
                            command := keymap.resolve(
                                context, name + "+" + key, app.settings
                            )
                        )
                    ),
                    None,
                )
                if command:
                    if command.target == "keyboard_passthrough":
                        self.toggle_passthrough()
                    elif (
                        app._screen_stack
                        and getattr(app.screen, "mod_context", None) == command.context
                    ):
                        app.prefix = False
                        await app.screen.run_action(command.target)
                    elif command.context.startswith("assistant") and isinstance(
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
                if (
                    command
                    and context == "palette"
                    and command.target
                    in ("cycle_previous", "cycle_next", "parent", "child")
                ):
                    await app.screen.run_action(command.target)
                    return
                if command and context == "content_search":
                    # Queue editing actions behind the focused Input's earlier
                    # characters instead of reading its value from the App queue.
                    canonical = {
                        "submit": "enter",
                        "next": "f3",
                        "previous": "shift+f3",
                        "close": "escape",
                    }[command.target]
                    await app._dispatch_native(events.Key(canonical, None))
                    return
                if command and context == "tasks":
                    await app.screen.run_action(command.target)
                    return
                if command and command.context.startswith("mod."):
                    await app.screen.run_action(command.target)
                    return
                if command and command.context.startswith("assistant"):
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
        if getattr(app.screen, "mod_context", None):
            return app.screen.mod_context
        if getattr(app.screen, "task_context", False):
            return "tasks"
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
        if isinstance(app.screen, PageJump):
            return "page_jump"
        if isinstance(app.screen, BottomSearch):
            return "content_search"
        if isinstance(app.screen, ActionDrawer):
            return "action_drawer"
        if isinstance(app.screen, StartMenu):
            return "start_menu"
        if app.view_focus is not None:
            return "surface"
        pane = app.active()
        if pane and pane.viewer:
            import base64
            import json

            if json.loads(base64.b64decode(pane.viewer)).get("kind") == "files":
                return "files"
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
            return parameters[0] in keymap.active_leader_chords(app.settings).values()
        return True

    async def action_leader(self, key, names=None):
        app = self.app
        logging.getLogger(__name__).debug("action_leader %s", key)
        if app.prefix and key == getattr(app, "prefix_chord", key):
            app.prefix = False
            await self._terminal_input()
            await app.backend.send(key)
        else:
            app.prefix = True
            app.prefix_chord = key
            app.prefix_names = (
                names
                or tuple(
                    name
                    for name, chord in keymap.active_leader_chords(app.settings).items()
                    if chord == key
                )
                or ("leader",)
            )

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
            await self._terminal_input()
            await app.backend.send(event.key, event.character)

    async def on_paste(self, event: events.Paste):
        app = self.app
        if app.screen is app._workspace_screen:
            from cosmos_tui.features.agent.control import human_input

            await human_input(app, app.active())
        if app.screen is app._workspace_screen:
            event.stop()
            if app.search is not None:
                app.search = (app.search + event.text)[:8192]
            elif not (app.active() and app.active().viewer):
                await app.backend.paste(event.text)
