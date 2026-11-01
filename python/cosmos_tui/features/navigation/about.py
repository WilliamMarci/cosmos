"""Project information in the shared compact pop-window style."""

from textual.binding import Binding
from textual.widgets import Static

from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.logo import render_logo_text
from cosmos_tui.ui.zones import Zone

from cosmos_tui.core.metadata import AUTHOR, DISPLAY_VERSION


class About(CosmosModal):
    zone = Zone.POP_WINDOW
    DEFAULT_CSS = """
    About { align: center middle; background: transparent; }
    #about-frame { width: 40; max-width: 90%; height: auto; max-height: 90%; }
    #about-content { height: auto; margin: 1 0; }
    """
    BINDINGS = [Binding("escape", "dismiss", show=False)]

    def compose(self):
        content = render_logo_text(self.app.theme_logo)
        content.append(f"\n\n{DISPLAY_VERSION}\nAuthor  {AUTHOR}")
        with Frame(id="about-frame") as frame:
            frame.border_title = "About"
            yield Static(content, id="about-content", markup=False)
