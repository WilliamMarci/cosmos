from textual.widgets import Static

from cosmos_tui.core.controller import Controller
from cosmos_tui.core.services import PowerlineValue
from cosmos_tui.features.assistant.bridge import AgentBridge
from cosmos_tui.features.assistant.presenter import Assistant


class AssistantLauncher(Controller):
    def __init__(self, app):
        super().__init__(app)
        self.bridge = None
        self.registered = set()
        self.prompt = ""
        self.passive = None
        self.passive_state = None

    async def start(self):
        self.bridge = AgentBridge(self.app)
        await self.bridge.start()

    async def close(self):
        if self.bridge:
            await self.bridge.close()

    async def open_command_assistant(self):
        app = self.app
        pane = app.active()
        if pane and pane.copy_mode:
            await app.action_error(
                "command assistant",
                "Leave history mode before opening the command assistant",
            )
            return
        if pane and app.screen is app._workspace_screen:
            ready = await app.backend.request(
                f"show-options -pqv -t {pane.id} @cosmos_terminal_agent"
            )
            program = await app.backend.request(
                f"display-message -p -t {pane.id} '#{{pane_current_command}}'"
            )
            if program != ["bash"]:
                app.message = "Return this pane to Bash to open the command assistant"
                return
            if ready != ["1"]:
                app.message = "Source terminal_agent/shell/agent.bash in this Bash, or create a new pane"
                return
            await app.backend.request(
                f"set-option -p -t {pane.id} @cosmos_agent_socket {app.backend.quote(self.bridge.path)}"
            )
            await app.backend.request(f"send-keys -t {pane.id} C-x C-a")
        return

    async def open_agent(self):
        from cosmos_tui.features.agent.launch import arguments

        app = self.app
        pane = app.active()
        command = arguments(app.backend, pane.id, self.prompt) if pane else None
        self.prompt = ""
        if pane:
            await app.session_windows.split(pane.id, command)
        app.panes = await app.backend.snapshot()
        return

    async def refresh(self, panes, terminal):
        app = self.app
        if self.bridge:
            for source_pane in panes:
                if source_pane.id not in self.registered:
                    await app.backend.request(
                        f"set-option -p -t {source_pane.id} @cosmos_agent_socket {app.backend.quote(self.bridge.path)}"
                    )
                    self.registered.add(source_pane.id)
            self.registered.intersection_update(p.id for p in panes)
        if isinstance(app.screen, Assistant):
            if any(p.id == app.screen.request["pane"] for p in panes):
                app.screen.place()
            else:
                await app.screen.action_cancel()
        passive = self.passive
        if passive and (
            not app.powerline.active or app.powerline.active.owner == "terminal_agent"
        ):
            app.powerline.publish(
                PowerlineValue("terminal_agent", passive["pane"], passive["request"])
            )
        elif not passive:
            app.powerline.release("terminal_agent")
        lease = app.powerline.active
        passive = dict(pane=lease.source_pane, request=lease.text) if lease else None
        source = next(
            (p for p in panes if passive and p.id == passive["pane"] and p.active),
            None,
        )
        passive_state = (
            (
                source.id,
                passive["request"],
                source.y + source.cursor[1],
                terminal.size.height,
            )
            if source and app.screen is app._workspace_screen
            else None
        )
        if passive_state != self.passive_state:
            self.passive_state = passive_state
            bar = app.query_one("#agent-powerline", Static)
            bar.display = passive_state is not None
            if passive_state:
                bar.styles.offset = (
                    0,
                    max(
                        0,
                        terminal.size.height
                        - (
                            2
                            if source.y + source.cursor[1] >= terminal.size.height - 1
                            else 1
                        ),
                    ),
                )
                bar.update(" › " + passive["request"])
