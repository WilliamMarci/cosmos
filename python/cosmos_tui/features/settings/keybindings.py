"""Compact keybinding settings backed by the command registry."""

from textual.binding import Binding
from textual.widgets import Static

from cosmos_tui.core import rpc
from cosmos_tui.input.keymap import bindings, validate
from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import Frame


class KeyBindingEditor(CosmosModal):
    DEFAULT_CSS = "KeyBindingEditor { align: center middle; background: transparent; } #key-editor { width: 62; height: auto; max-width: 92%; } #key-value { height: 1; border: none; padding: 0; } #key-error { height: auto; }"
    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, command):
        super().__init__()
        self.command = command

    def compose(self):
        with Frame(id="key-editor") as frame:
            frame.set_heading(self.command.label, self.command.id)
            yield Static("Comma-separated keys; empty restores defaults", markup=False)
            yield CosmosInput(
                ", ".join(bindings(self.command, self.app.settings)), id="key-value"
            )
            yield Static("", id="key-error", markup=False)

    def on_mount(self):
        self.query_one(CosmosInput).focus()

    async def on_input_submitted(self, event):
        settings = await rpc.call("settings.get")
        overrides = dict(settings.get("keybindings", {}))
        value = self.query_one(CosmosInput).value.strip()
        if value:
            overrides[self.command.id] = [k.strip() for k in value.split(",")]
        else:
            overrides.pop(self.command.id, None)
        try:
            validate(overrides)
            settings["keybindings"] = overrides
            await rpc.call("settings.replace", settings)
            self.app.settings = settings
            self.dismiss(True)
        except (ValueError, RuntimeError) as error:
            self.query_one("#key-error", Static).update(str(error))

    def action_close(self):
        self.dismiss(False)
