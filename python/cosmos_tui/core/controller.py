"""Shared controller lifetime contract. Controllers compose the UI host."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cosmos_tui.app import Cosmos


class Controller:
    def __init__(self, app: "Cosmos"):
        self.app = app
