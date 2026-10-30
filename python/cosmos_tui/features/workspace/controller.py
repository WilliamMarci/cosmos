import logging

from cosmos_tui.core import rpc
from cosmos_tui.core.controller import Controller
from cosmos_tui.features.assistant.presenter import Assistant
from cosmos_tui.features.navigation.about import About
from cosmos_tui.features.navigation.menus import ActionDrawer, StartMenu
from cosmos_tui.features.navigation.switcher import Switcher
from cosmos_tui.features.navigation.session_prompt import NewSession
from cosmos_tui.features.notifications.toast import NoticeToast
from cosmos_tui.features.search.bar import BottomSearch
from cosmos_tui.features.reader.jump import PageJump
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.theme.panel import ThemePanel
from cosmos_tui.input import keymap
from cosmos_tui.ui.help import Help
from cosmos_tui.ui.menus import CompactMenu


class WorkspaceController(Controller):
    async def toggle_mouse_passthrough(self):
        app = self.app
        try:
            settings = await rpc.call("settings.get")
            value = not settings.get("mouse_passthrough", True)
            settings["mouse_passthrough"] = value
            await rpc.call("settings.replace", settings)
            actual = await rpc.call("settings.get")
            if actual.get("mouse_passthrough") != value:
                raise RuntimeError(
                    "Coordinator did not retain mouse_passthrough; update/restart the coordinator and retry"
                )
            app.settings = actual
        except (RuntimeError, OSError, ValueError) as error:
            await app.action_error("mouse passthrough", error)

    def show_pane_numbers(self):
        self.identifying = True
        if getattr(self, "identify_timer", None):
            self.identify_timer.stop()
        self.identify_timer = self.app.set_timer(3, self.hide_pane_numbers)
        self.app.query_one("#terminal").refresh()

    def hide_pane_numbers(self):
        self.identifying = False
        self.app.query_one("#terminal").refresh()

    async def identify_key(self, event):
        if not getattr(self, "identifying", False):
            return False
        self.hide_pane_numbers()
        if self.app.screen is not self.app._workspace_screen:
            return False
        digit = event.character or event.key
        if len(digit) == 1 and digit in "0123456789":
            pane = next((p for p in self.app.panes if p.index == int(digit)), None)
            if pane:
                await self.app.backend.request("select-pane -t " + pane.id)
                self.app.panes = await self.app.backend.snapshot()
            return True
        return event.key == "escape"

    async def action_leader_key(self, key):
        if key in ("resume_control", "end_control"):
            import asyncio
            from cosmos_tui.features.agent.control import ControlStore

            pane = self.app.active()
            if pane:
                await asyncio.to_thread(
                    ControlStore(self.app.backend.argv[2]).change,
                    pane.id,
                    "resume" if key == "resume_control" else "cancel",
                )
            return
        if key == "private_pane":
            pane = self.app.active()
            if pane:
                current = await self.app.backend.request(
                    f"show-options -pqv -t {pane.id} @cosmos_private"
                )
                enabled = current not in (["1"], ["on"], ["true"])
                await self.app.backend.request(
                    f"set-option -p -t {pane.id} @cosmos_private {int(enabled)}"
                )
                await self.app.notification_events.publish(
                    "Pane private · Agent access disabled"
                    if enabled
                    else "Pane privacy disabled",
                    source="workspace",
                    level="info",
                )
            return
        if key == "keyboard_passthrough":
            self.app.inputs.toggle_passthrough()
            return
        app = self.app
        logging.getLogger(__name__).debug("action_leader_key %s", key)
        app.prefix = False
        if key in ("copy_mode", "history_search", "paste_buffer"):
            pane = app.active()
            if not pane or pane.viewer or app.screen is not app._workspace_screen:
                return
            try:
                if key == "paste_buffer":
                    if pane.copy_mode:
                        await app.backend.request(f"send-keys -X -t {pane.id} cancel")
                    await app.backend.request(f"paste-buffer -p -t {pane.id}")
                else:
                    await app.backend.request(f"copy-mode -t {pane.id}")
                app.panes = await app.backend.snapshot()
                if key == "history_search":
                    await app.copy_action("search")
            except RuntimeError as error:
                await app.action_error(key, error)
            return
        if key == "identify_panes":
            self.show_pane_numbers()
            return
        if key == "start":
            app.action_start_menu()
            return
        if key == "actions":
            app.action_context_actions()
            return
        if key in ("ime_enable", "ime_disable"):
            desired = key == "ime_enable"
            if app.ime.enabled != desired:
                await app.ime.toggle()
            return
        if key == "ime_toggle":
            await app.ime.toggle()
            return
        if key == "ime_width":
            await app.ime.toggle_width()
            return
        if key == "mouse_passthrough":
            await self.toggle_mouse_passthrough()
            return
        if key == "quit":
            await app.detach("exit")
            return
        if key == "d":
            await app.detach()
            return
        if key == "a":
            await app.assistant_ui.open_command_assistant()
            return
        if key == "g":
            await app.assistant_ui.open_agent()
            return
        if key == "N":
            notices = await rpc.call("notifications.active", {"client": app.client})
            if notices:
                choices = []
                for notice in reversed(notices):
                    label = notice["text"][:40]
                    choices.extend(
                        (
                            f"{notice['id']}:{action['id']}",
                            label + " · " + action["label"],
                        )
                        for action in notice.get("actions", [])
                    )
                    choices.append(
                        (f"{notice['id']}:__dismiss__", label + " · Dismiss here")
                    )

                def choose(action):
                    if action:
                        notification, _, selected = action.partition(":")
                        app.run_worker(
                            app.on_notice_toast_action(
                                NoticeToast.Action(int(notification), selected)
                            )
                        )

                app.pop_windows.actions("Notifications", choices, choose)
            return
        if key == "full_stop":
            if isinstance(app.screen, Assistant):
                app.screen.action_actions()
            return
        if key == "new_session":
            app.push_screen(NewSession())
            return
        if key == "files":
            await app.navigation.open_files()
            return
        if key == "s":
            app.push_screen(Switcher())
            return
        if key == "p":
            app.push_screen(Palette())
            return
        if key == "question_mark":
            if app.key_context() == "copy":
                app.push_screen(
                    Help("History / selection", keymap.help_rows("copy", app.settings))
                )
                return
            if isinstance(app.screen, Assistant):
                app.push_screen(
                    Help(
                        "Command suggestions",
                        keymap.help_rows(app.key_context(), app.settings),
                    )
                )
                return
            if isinstance(
                app.screen,
                (
                    Palette,
                    ThemePanel,
                    CompactMenu,
                    About,
                    BottomSearch,
                    PageJump,
                    KeyBindingEditor,
                    ActionDrawer,
                    StartMenu,
                ),
            ):
                app.push_screen(
                    Help("Actions", keymap.help_rows(app.key_context(), app.settings))
                )
                return
            if isinstance(app.screen, Switcher):
                app.push_screen(
                    Help(
                        "Switch",
                        keymap.help_rows("switch", app.settings)
                        + [("Type", "filter sessions / windows")],
                    )
                )
                return
            app.push_screen(
                Help(
                    {"files": "Files", "viewer": "Viewer"}.get(
                        app.key_context(), "Workspace"
                    ),
                    keymap.help_rows(app.key_context(), app.settings),
                )
            )
            return
        command = {
            "c": "new-window",
            "percent_sign": "split-window -h",
            "quotation_mark": "split-window -v",
            "vertical_line": "split-window -h",
            "minus": "split-window -v",
            "H": "resize-pane -L 5",
            "J": "resize-pane -D 5",
            "K": "resize-pane -U 5",
            "L": "resize-pane -R 5",
            "n": "next-window",
            "b": "previous-window",
            "o": "select-pane -t :.+",
            "z": "resize-pane -Z",
            "up": "select-pane -U",
            "down": "select-pane -D",
            "left": "select-pane -L",
            "right": "select-pane -R",
        }.get(key)
        if key.isdigit():
            command = f"select-window -t :{key}"
        if command:
            if app.screen is not app._workspace_screen:
                return
            pane = app.active()
            if pane and command.startswith(
                ("split-window", "select-pane", "resize-pane")
            ):
                name, _, arguments = command.partition(" ")
                command = f"{name} -t {pane.id} {arguments}"
            logging.getLogger(__name__).debug("layout %s", command)
            try:
                await app.backend.request(command)
                app.panes = await app.backend.snapshot()
            except RuntimeError as error:
                await app.action_error(command, error)
