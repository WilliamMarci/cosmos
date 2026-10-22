"""Compact bottom content search shared by PDF, pane history and future providers."""

from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static

from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import BottomSheet, MiniAction, SheetShadow
from cosmos_tui.ui.zones import Zone


class BottomSearch(CosmosModal):
    zone = Zone.BOTTOM_POWERLINE
    DEFAULT_CSS = """
    BottomSearch { background: transparent; background-tint: transparent; }
    #search-sheet { position: absolute; height: 2; width: 100%; padding: 0; }
    #content-search { height: 1; width: 100%; padding: 0; }
    #content-search-label { width: auto; height: 1; }
    #content-search-query { width: 1fr; height: 1; border: none; padding: 0; }
    #content-search-result { width: auto; max-width: 30%; height: 1; }
    """
    BINDINGS = [Binding("escape", "close", show=False)]

    def __init__(self, label, provider, *, initial="", steps=False):
        super().__init__()
        self.styles.background = "transparent"
        self.styles.background_tint = "transparent"
        self.label, self.provider, self.initial, self.steps = (
            label,
            provider,
            initial,
            steps,
        )
        self.busy = False

    def compose(self):
        yield SheetShadow(id="search-shadow")
        with BottomSheet(id="search-sheet") as sheet:
            sheet.set_heading(self.label + " search")
            yield from self.search_row()

    def search_row(self):
        with Horizontal(id="content-search"):
            yield Static(" / ", id="content-search-label")
            yield CosmosInput(
                self.initial, placeholder="Search content", id="content-search-query"
            )
            yield Static("", id="content-search-result", markup=False)
            if self.steps:
                yield MiniAction("↑", id="content-search-previous")
                yield MiniAction("↓", id="content-search-next")
            yield MiniAction("↵", id="content-search-submit")
            yield MiniAction("×", id="content-search-close")

    def place(self):
        bar = self.app.query_one("#status", Static)
        row = self.query_one("#content-search")
        sheet = self.query_one(BottomSheet)
        y = max(0, self.app.size.height - int(bar.display) - 2)
        sheet.apply_theme(self.app.role_colors)
        self.query_one(SheetShadow).place(sheet, 0, y, self.app.size.width, 2)
        palette = self.app.role_colors
        row.styles.background, row.styles.color = palette["base"], palette["fg"]
        for button in self.query(MiniAction):
            button.apply_theme(palette)

    def on_mount(self):
        self.place()
        self.query_one(CosmosInput).focus()

    def on_resize(self):
        if self.is_mounted:
            self.place()

    async def apply(self, direction=0):
        if self.busy:
            return
        self.busy = True
        try:
            query = self.query_one(CosmosInput).value[:8192]
            result = await self.provider(query, direction)
            self.query_one("#content-search-result", Static).update(
                " " + (result or "") + " "
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.query_one("#content-search-result", Static).update(str(error))
        finally:
            self.busy = False

    async def on_input_submitted(self, event):
        await self.apply()

    async def action_submit(self):
        await self.apply()

    async def action_next(self):
        if self.steps:
            await self.apply(1)

    async def action_previous(self):
        if self.steps:
            await self.apply(-1)

    def action_close(self):
        self.dismiss(None)

    async def on_mini_action_pressed(self, event):
        event.stop()
        name = event.button.id.rsplit("-", 1)[-1]
        await self.run_action(name)
