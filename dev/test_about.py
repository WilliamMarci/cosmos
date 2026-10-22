"""Exercise About through the real command palette and shared frame."""

from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
import xml.etree.ElementTree as ET

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / p) for p in ("python", "terminal_agent")
]
from cosmos_tui.app import Cosmos  # noqa: E402
from cosmos_tui.app import Palette  # noqa: E402
from cosmos_tui.features.navigation.about import About, VERSION, AUTHOR  # noqa: E402


class Probe(Cosmos):
    CSS = Cosmos.CSS
    settings = {"theme": "dark", "leader": "C-b"}

    async def on_mount(self, event):
        event.prevent_default()
        await self.push_screen(Palette())

    async def on_unmount(self, event):
        event.prevent_default()


class AboutTests(unittest.IsolatedAsyncioTestCase):
    async def test_palette_about_shows_logo_metadata_and_returns_to_palette(self):
        snapshot = dict(actions=[], mods=[], settings=Probe.settings)
        with patch("cosmos_tui.core.rpc.call", new=AsyncMock(return_value=snapshot)):
            app = Probe()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.press(*"about", "enter")
                await pilot.pause()
                self.assertIsInstance(app.screen, About)
                root = ET.fromstring(app.export_screenshot())
                text = "".join(
                    n.text or "" for n in root.iter() if n.tag.endswith("}text")
                ).replace("\xa0", " ")
                self.assertIn("Cosmos " + VERSION, text)
                self.assertIn("Author  " + AUTHOR, text)
                self.assertIn("░", text)
                self.assertLessEqual(
                    app.screen.query_one("#about-frame").region.width, 40
                )
                await pilot.press("escape")
                self.assertIsInstance(app.screen, Palette)


if __name__ == "__main__":
    unittest.main()
