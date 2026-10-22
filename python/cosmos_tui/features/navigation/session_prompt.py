"""Create and select a retained session through the shared bottom overlay."""

from textual.binding import Binding
from textual.widgets import Static

from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.terminal.sessions import create
from cosmos_tui.ui.chrome import BottomSheet, SheetShadow


class NewSession(CosmosModal):
    BINDINGS = [Binding("escape", "cancel", show=False)]
    DEFAULT_CSS = """
    #new-session-sheet { position: absolute; width: 100%; height: 3; padding: 0 1; }
    #new-session-name { height: 1; border: none; padding: 0; }
    #new-session-error { height: 1; }
    """

    def __init__(self):
        super().__init__()
        self.styles.background = "transparent"
        self.styles.background_tint = "transparent"
        self.busy = False

    def compose(self):
        yield SheetShadow(id="new-session-shadow")
        with BottomSheet(id="new-session-sheet") as sheet:
            sheet.set_heading("New session", "workspace.new_session")
            yield CosmosInput(
                placeholder="Session name · Enter to create · Esc to cancel",
                id="new-session-name",
            )
            yield Static("", id="new-session-error", markup=False)

    def on_mount(self):
        self.place()
        self.query_one(CosmosInput).focus()

    def place(self):
        bottom = self.app.size.height - int(self.app.query_one("#status").display)
        self.query_one(SheetShadow).place(
            self.query_one(BottomSheet), 0, max(0, bottom - 3), self.app.size.width, 3
        )

    def on_resize(self):
        if self.is_mounted:
            self.place()

    async def on_input_submitted(self, event):
        if self.busy:
            return
        self.busy = True
        name = event.value.strip()
        try:
            await create(name)
            windows = await self.app.backend.inventory()
            window = next(row for row in windows if row["session"] == name)
            await self.app.backend.select_window(window)
            self.app.panes = await self.app.backend.snapshot()
            self.dismiss(None)
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            self.query_one("#new-session-error", Static).update(str(error))
        finally:
            self.busy = False

    def action_cancel(self):
        if not self.busy:
            self.dismiss(None)
