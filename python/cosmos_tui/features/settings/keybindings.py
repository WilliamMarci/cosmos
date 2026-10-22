"""Explicit shortcut phases, with one row per alternative binding."""

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static
from cosmos_tui.core import rpc
from cosmos_tui.input.keymap import bindings, validate
from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import Frame, MiniAction
from cosmos_tui.ui.keyboard import KeyboardPreview, key_legend


class KeyBindingEditor(CosmosModal):
    DEFAULT_CSS = """
    KeyBindingEditor { align: center middle; }
    #key-editor { width: 76; height: auto; max-width: 94%; max-height: 94%; }
    #binding-fields { height: auto; max-height: 12; overflow-y: auto; }
    .binding-phase { height: 1; }
    .binding-phase CosmosInput { width: 1fr; height: 1; border: none; padding: 0; }
    .phase-arrow { width: 3; height: 1; }
    #key-error { height: auto; }
    #key-buttons { height: 1; }
    """
    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.count = 0
        self.ready = False

    def fields(self, value):
        first, second = (
            ("leader", value[7:]) if value.startswith("leader+") else (value, "")
        )
        index = self.count
        self.count += 1
        suffix = "" if index == 0 else f"-{index}"
        with Horizontal(classes="binding-phase"):
            yield CosmosInput(
                first, id="key-value" + suffix, placeholder="First press / chord"
            )
            yield Static(" → ", classes="phase-arrow")
            yield CosmosInput(
                second, id="key-next" + suffix, placeholder="Next press (Leader only)"
            )

    def compose(self):
        with Frame(id="key-editor") as frame:
            frame.set_heading(self.command.label, self.command.id)
            yield Static(
                "First → next press · + combines keys · each row is an alternative.",
                markup=False,
            )
            yield Static(
                f"Leader = {self.app.settings.get('leader', 'C-b').replace('C-', 'Ctrl+')} · ↺ restores defaults.",
                markup=False,
            )
            with Vertical(id="binding-fields"):
                for value in bindings(self.command, self.app.settings) or ("",):
                    yield from self.fields(value)
            yield Static("", id="key-error", markup=False)
            with Horizontal(id="key-buttons"):
                yield MiniAction("+", id="key-add")
                yield MiniAction("↺", id="key-reset")
                yield MiniAction("✓", id="key-save")
            legend = Static(key_legend(self.app.role_colors), id="editor-key-legend")
            legend.styles.height = 1
            yield legend
            yield KeyboardPreview(bindings(self.command, self.app.settings))

    def values(self):
        values = []
        aliases = {",": "comma", ".": "full_stop", "+": "plus", "?": "question_mark"}
        for index in range(self.count):
            suffix = "" if index == 0 else f"-{index}"
            first = self.query_one("#key-value" + suffix, CosmosInput).value.strip()
            second = self.query_one("#key-next" + suffix, CosmosInput).value.strip()
            if not first and not second:
                continue
            if first.lower() == "leader":
                if not second:
                    raise ValueError("Leader requires a next press")
                values.append("leader+" + aliases.get(second, second))
            else:
                if second:
                    raise ValueError(
                        "Two-stage bindings currently require Leader as the first press"
                    )
                values.append(aliases.get(first, first))
        return values

    def on_mount(self):
        self.ready = True
        self.query_one(CosmosInput).focus()
        self.fit()

    async def on_input_submitted(self, event):
        await self.save()

    async def save(self, reset=False):
        try:
            settings = await rpc.call("settings.get")
            overrides = dict(settings.get("keybindings", {}))
            values = [] if reset else self.values()
            if values:
                overrides[self.command.id] = values
            else:
                overrides.pop(self.command.id, None)
            validate(overrides)
            settings["keybindings"] = overrides
            await rpc.call("settings.replace", settings)
            self.app.settings = settings
            self.dismiss(True)
        except (ValueError, RuntimeError, OSError) as error:
            self.query_one("#key-error", Static).update(str(error))

    async def on_mini_action_pressed(self, event):
        event.stop()
        if event.button.id == "key-add":
            from textual.containers import Horizontal

            # Build the same two-field row without delimiter parsing.
            suffix = f"-{self.count}"
            self.count += 1
            row = Horizontal(classes="binding-phase")
            await self.query_one("#binding-fields").mount(row)
            await row.mount(
                CosmosInput(id="key-value" + suffix, placeholder="First press / chord"),
                Static(" → ", classes="phase-arrow"),
                CosmosInput(
                    id="key-next" + suffix, placeholder="Next press (Leader only)"
                ),
            )
            row.query_one(CosmosInput).focus()
        else:
            await self.save(reset=event.button.id == "key-reset")

    def action_close(self):
        self.dismiss(False)

    def fit(self):
        self.query_one(KeyboardPreview).fit()
        self.query_one("#editor-key-legend").display = self.query_one(
            KeyboardPreview
        ).display
        for button in self.query(MiniAction):
            button.apply_theme(self.app.role_colors)

    def on_resize(self):
        if self.ready:
            self.fit()

    def on_input_changed(self, event):
        if not self.ready:
            return
        # Direct chords have no second stage. Switching away from Leader clears it.
        if (
            event.input.id
            and event.input.id.startswith("key-value")
            and event.value.lower() != "leader"
        ):
            suffix = event.input.id[len("key-value") :]
            self.query_one("#key-next" + suffix, CosmosInput).value = ""
        try:
            self.query_one(KeyboardPreview).present(self.values())
            self.query_one("#key-error", Static).update("")
        except ValueError as error:
            self.query_one("#key-error", Static).update(str(error))
