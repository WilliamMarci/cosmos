"""Shared compact bottom text prompt for names and file operations."""

from cosmos_tui.features.search.bar import BottomSearch
from cosmos_tui.input.shortcuts import CosmosInput
from cosmos_tui.ui.chrome import BottomSheet


class TextPrompt(BottomSearch):
    def on_mount(self):
        super().on_mount()
        self.query_one(BottomSheet).set_heading(self.label)
        self.query_one(CosmosInput).placeholder = "Name"

    async def apply(self, direction=0, query=None):
        value = self.query_one(CosmosInput).value if query is None else query
        if not value:
            return
        self.dismiss(None)
        await self.provider(value, 0)
