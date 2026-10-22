"""Two independent theme lists with one shared preview and explicit save."""

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, ListView, ListItem, Label
from cosmos_tui.core import rpc
from cosmos_tui.features.theme.palettes import TERMINALS, INTERFACES, terminal_palette
from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.chrome import Frame, MiniAction
from cosmos_tui.ui.styles import DARK, LIGHT


class ThemePanel(CosmosModal):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("tab", "app.focus_next", show=False),
        Binding("shift+tab", "app.focus_previous", show=False),
        Binding("ctrl+s", "save", show=False),
    ]
    DEFAULT_CSS = """
    ThemePanel { align: center middle; background: transparent; }
    #theme-panel { width: 82; max-width: 94%; height: 26; max-height: 94%; }
    #theme-columns { height: 1fr; min-height: 6; }
    .theme-column { width: 1fr; }
    .theme-heading { height: 1; }
    #terminal-themes, #ui-themes { height: 1fr; margin: 0; }
    #theme-preview { height: 9; border: solid #62a0e6; padding: 0 1; }
    #theme-buttons { height: 1; }
    #theme-error { height: auto; }
    #theme-hint { width: 1fr; height: 1; }
    """

    def __init__(self):
        super().__init__()
        self.ready = False
        self.saving = False

    def compose(self):
        with Frame(id="theme-panel") as frame:
            frame.set_heading("Theme")
            with Horizontal(id="theme-columns"):
                with Vertical(classes="theme-column"):
                    yield Label("Terminal content", classes="theme-heading")
                    yield ListView(id="terminal-themes")
                with Vertical(classes="theme-column"):
                    yield Label("Cosmos interface", classes="theme-heading")
                    yield ListView(id="ui-themes")
            yield Static("", id="theme-preview", markup=False)
            yield Static("", id="theme-error", markup=False)
            with Horizontal(id="theme-buttons"):
                yield Static("Tab: switch column · select to preview", id="theme-hint")
                yield MiniAction("✓", id="theme-save")
                yield MiniAction("×", id="theme-cancel")

    async def on_mount(self):
        for selector, choices, selected in [
            (
                "#terminal-themes",
                TERMINALS,
                self.app.settings.get("terminal_theme", "inherit"),
            ),
            ("#ui-themes", INTERFACES, self.app.settings.get("theme", "dark")),
        ]:
            listing = self.query_one(selector, ListView)
            await listing.extend(ListItem(Label(label)) for _, label in choices)
            listing.index = next(
                (i for i, (key, _) in enumerate(choices) if key == selected), 0
            )
        self.ready = True
        self.preview()
        self.query_one("#terminal-themes").focus()
        self.call_after_refresh(self.preview)
        for button in self.query(MiniAction):
            button.apply_theme(self.app.role_colors)

    def selected(self):
        return TERMINALS[self.query_one("#terminal-themes", ListView).index or 0][
            0
        ], INTERFACES[self.query_one("#ui-themes", ListView).index or 0][0]

    def preview(self):
        terminal, interface = self.selected()
        palette = LIGHT if interface == "light" else DARK
        colors = terminal_palette(terminal)
        # Native default SGR values render through the caller terminal, including SSH.
        inherited = terminal == "inherit"
        fg, bg = colors["fg"], colors["bg"]
        width = max(10, self.query_one("#theme-preview").size.width - 4)
        text = Text(
            "Terminal · "
            + ("actual colors follow your terminal" if inherited else terminal)
            + "\n",
            style=palette["mute"],
        )
        text.append(
            " user@host:~/project $ ".ljust(width) + "\n", style=f"{fg} on {bg}"
        )
        native = [
            "black",
            "red",
            "green",
            "yellow",
            "blue",
            "magenta",
            "cyan",
            "white",
            "bright_black",
            "bright_red",
            "bright_green",
            "bright_yellow",
            "bright_blue",
            "bright_magenta",
            "bright_cyan",
            "bright_white",
        ]
        for index, color in enumerate(colors["ansi"] or native):
            text.append(" ■ ", style=color)
            if index == 7:
                text.append("\n")
        text.append("\nCosmos interface\n", style=palette["fg"])
        text.append(" Settings ", style=f"{palette['on']} on {palette['acc']}")
        text.append("  Preview · notifications · input method", style=palette["fg"])
        preview = self.query_one("#theme-preview", Static)
        preview.styles.background, preview.styles.color = palette["base"], palette["fg"]
        preview.update(text)

    def on_list_view_highlighted(self, event):
        if self.ready:
            self.preview()

    def on_list_view_selected(self, event):
        event.stop()
        if self.ready:
            self.preview()

    async def on_mini_action_pressed(self, event):
        event.stop()
        if event.button.id == "theme-save":
            await self.save()
        else:
            self.action_cancel()

    async def save(self):
        if self.saving:
            return
        self.saving = True
        try:
            settings = await rpc.call("settings.get")
            settings["terminal_theme"], settings["theme"] = self.selected()
            await rpc.call("settings.replace", settings)
            self.app.settings = settings
            self.app.query_one("#terminal").refresh()
            self.dismiss(True)
        except (OSError, RuntimeError) as error:
            await self.app.action_error("settings.theme", error)
        finally:
            self.saving = False

    def action_cancel(self):
        if not self.saving:
            self.dismiss(False)

    def on_resize(self):
        if self.ready:
            self.call_after_refresh(self.preview)

    async def action_save(self):
        await self.save()
