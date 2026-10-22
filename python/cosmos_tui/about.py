"""Project information in the shared compact pop-window style."""

from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from .chrome import Frame
from .shortcuts import CosmosModal
from .surfaces import Zone

VERSION = "0.1.0"
AUTHOR = "amadeus"


class About(CosmosModal):
    zone = Zone.POP_WINDOW
    DEFAULT_CSS = """
    About { align: center middle; background: transparent; }
    #about-frame { width: 40; max-width: 90%; height: auto; max-height: 90%; }
    #about-content { height: auto; margin: 1 0; }
    """
    BINDINGS = [Binding("escape", "dismiss", show=False)]

    def compose(self):
        logo = (Path(__file__).parent / "assets/cosmos-logo.ansi").read_text()
        content = Text.from_ansi(logo.rstrip())
        content.append(f"\n\nCosmos {VERSION}\nAuthor  {AUTHOR}")
        with Frame(id="about-frame") as frame:
            frame.border_title = "About"
            yield Static(content, id="about-content", markup=False)
