"""Two independent theme lists with one shared preview and explicit save."""

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, ListView, ListItem, Label
from cosmos_tui.core import rpc
from cosmos_tui.features.theme.catalog import (
    cosmos_choices,
    cosmos_theme,
    reload_themes,
    terminal_choices,
)
from cosmos_tui.features.theme.controller import apply_interface
from cosmos_tui.features.theme.palettes import terminal_palette
from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.blocks import gradient_block
from cosmos_tui.ui.chrome import Frame, MiniAction


class ThemePanel(CosmosModal):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("tab", "app.focus_next", show=False),
        Binding("shift+tab", "app.focus_previous", show=False),
        Binding("ctrl+s", "save", show=False),
        Binding("r", "reload", show=False),
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
        self.terminals = []
        self.interfaces = []
        self.errors = ()

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
                yield Static(
                    "Tab: switch column · r: reload themes", id="theme-hint"
                )
                yield MiniAction("✓", id="theme-save")
                yield MiniAction("×", id="theme-cancel")

    @staticmethod
    def _with_current(choices, current, kind):
        if current and current not in {key for key, _ in choices}:
            choices.append((current, f"{kind} · missing · {current}"))
        return choices

    async def populate(self):
        if self.ready:
            terminal, interface = self.selected()
        else:
            terminal = self.app.settings.get("terminal_theme", "inherit")
            interface = self.app.settings.get("theme", "dark")
        reload_themes()
        self.terminals = self._with_current(
            terminal_choices(), terminal, "Terminal"
        )
        self.interfaces = self._with_current(
            cosmos_choices(), interface, "Interface"
        )
        for selector, choices, selected in [
            ("#terminal-themes", self.terminals, terminal),
            ("#ui-themes", self.interfaces, interface),
        ]:
            listing = self.query_one(selector, ListView)
            await listing.clear()
            await listing.extend(ListItem(Label(label)) for _, label in choices)
            listing.index = next(
                (index for index, (key, _) in enumerate(choices) if key == selected),
                0,
            )
        self.ready = True
        self.show_errors()
        self.preview()
        if not self.query_one("#terminal-themes", ListView).has_focus:
            self.query_one("#terminal-themes", ListView).focus()
        self.call_after_refresh(self.preview)
        for button in self.query(MiniAction):
            button.apply_theme(self.app.role_colors)

    def show_errors(self):
        error = self.query_one("#theme-error", Static)
        error.display = bool(self.errors)
        if self.errors:
            shown = " · ".join(self.errors[:2])
            more = f" (+{len(self.errors) - 2})" if len(self.errors) > 2 else ""
            error.styles.color = self.app.role_colors["mute"]
            error.update("Theme files: " + shown + more)

    async def on_mount(self):
        await self.populate()
        self.query_one("#terminal-themes").focus()
        for button in self.query(MiniAction):
            button.apply_theme(self.app.role_colors)

    def selected(self):
        terminal = self.terminals[
            self.query_one("#terminal-themes", ListView).index or 0
        ][0]
        interface = self.interfaces[self.query_one("#ui-themes", ListView).index or 0][
            0
        ]
        return terminal, interface

    def preview(self):
        terminal, interface = self.selected()
        theme = cosmos_theme(interface)
        palette = theme.palette
        colors = terminal_palette(terminal)
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
        text.append(
            gradient_block("COSMOS", theme.logo.foreground, theme.logo.background)
        )
        text.append("  Settings", style=f"{palette['on']} on {palette['acc']}")
        text.append("\nIcon ")
        for color in (*theme.logo.foreground, *theme.logo.background):
            text.append(" ■ ", style=color)
        text.append("  Preview · notifications · input method", style=palette["fg"])
        preview = self.query_one("#theme-preview", Static)
        preview.styles.background, preview.styles.color = palette["bg"], palette["fg"]
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
            terminal, interface = self.selected()
            settings = await rpc.call("settings.get")
            settings["terminal_theme"], settings["theme"] = terminal, interface
            await rpc.call("settings.replace", settings)
            actual = await rpc.call("settings.get")
            if (
                actual.get("terminal_theme") != terminal
                or actual.get("theme") != interface
            ):
                raise RuntimeError(
                    "Coordinator did not retain the selected themes; update/restart the coordinator and retry"
                )
            self.app.settings = actual
            theme = cosmos_theme(interface)
            self.app.role_colors = theme.palette
            self.app.theme_logo = theme.logo
            self.app.theme_is_light = theme.light
            self.app._interface_theme_state = None
            apply_interface(self.app)
            self.app.query_one("#terminal").refresh()
            self.dismiss(True)
        except (OSError, RuntimeError) as error:
            await self.app.action_error("settings.theme", error)
        finally:
            self.saving = False

    def action_cancel(self):
        if not self.saving:
            self.dismiss(False)

    async def action_reload(self):
        await self.populate()

    def on_resize(self):
        if self.ready:
            self.call_after_refresh(self.preview)

    async def action_save(self):
        await self.save()
