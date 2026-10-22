"""Compact bottom page-number prompt, independent of content search."""

from textual.binding import Binding
from textual.widgets import Static
from cosmos_tui.input.shortcuts import CosmosInput, CosmosModal
from cosmos_tui.ui.chrome import BottomSheet, SheetShadow
from cosmos_tui.ui.placement import bottom_input_rect, PaneInputSurface
from cosmos_tui.ui.zones import Zone


class PageJump(PaneInputSurface, CosmosModal):
    input_rows = 3
    preserve_workspace_graphics = True
    zone = Zone.SESSION_WINDOW
    BINDINGS = [Binding("escape", "cancel", show=False)]
    DEFAULT_CSS = """
    #page-jump { position: absolute; width: 100%; height: 3; padding: 0 1; }
    #jump-value { height: 1; border: none; padding: 0; }
    #jump-error { height: 1; }
    """

    def __init__(self, page, pages, submit, *, bounds=None):
        super().__init__()
        self.styles.background = "transparent"
        self.styles.background_tint = "transparent"
        self.page, self.pages, self.submit = page, pages, submit
        self.bounds = bounds

    def compose(self):
        yield SheetShadow(id="jump-shadow")
        with BottomSheet(id="page-jump") as sheet:
            sheet.set_heading(f"Go to page · 1–{self.pages}", "viewer.jump")
            yield CosmosInput(str(self.page), id="jump-value", select_on_focus=True)
            yield Static("", id="jump-error", markup=False)

    def on_mount(self):
        self.place()
        self.query_one(CosmosInput).focus()

    def place(self):
        rect = bottom_input_rect(self.app, 3, self.bounds)
        if rect is None:
            self.dismiss(None)
            return
        self.query_one(SheetShadow).place(
            self.query_one(BottomSheet), *rect, contained=self.bounds is not None
        )

    def on_resize(self):
        if self.is_mounted:
            self.place()

    async def on_input_submitted(self, event):
        try:
            page = int(event.value)
            if not 1 <= page <= self.pages:
                raise ValueError(f"Enter a page between 1 and {self.pages}")
            await self.submit(page)
            self.dismiss(None)
        except (ValueError, RuntimeError, OSError) as error:
            self.query_one("#jump-error", Static).update(str(error))

    def action_cancel(self):
        self.dismiss(None)
