"""Command island must preserve reader images in other terminal panes."""

from types import SimpleNamespace
import unittest
from PIL import Image

from test_assistant import LayerProbe
from cosmos_tui.features.assistant.presenter import Assistant
from cosmos_tui.ui.cells import Rect


class AssistantGraphicsTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_keeps_placements_and_masks_only_overlap(self):
        app = LayerProbe()
        cleared = []
        original = app.graphics.commit
        app.graphics.commit = lambda images: cleared.append(images)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assistant = app.screen
            self.assertIsInstance(assistant, Assistant)
            self.assertTrue(assistant.preserve_workspace_graphics)
            self.assertNotIn([], cleared)
            app.graphics.commit = original
            app.reader_ui.cell_pixels = lambda: (1, 1)
            assistant.layout_data = SimpleNamespace(bounds=Rect(0, 1, 40, 2))
            image = Image.new("RGB", (40, 20), "white")
            other = SimpleNamespace(id="%other", x=50, y=0)
            self.assertIs(assistant.cover_reader_image(image, other), image)
            overlapping = SimpleNamespace(id="%overlap", x=0, y=0)
            masked = assistant.cover_reader_image(image, overlapping)
            self.assertEqual(masked.getpixel((0, 0)), (255, 255, 255))
            self.assertNotEqual(masked.getpixel((0, 1)), (255, 255, 255))
            self.assertEqual(masked.getpixel((0, 3)), (255, 255, 255))
            assistant.layout_data = None
