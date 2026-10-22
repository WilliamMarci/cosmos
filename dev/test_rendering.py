"""A suppressed Textual display batch must not discard queued Kitty images."""

import os
from unittest.mock import patch
import sys
import unittest
from pathlib import Path

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / n) for n in ("python", "terminal_agent")
]
from cosmos_tui.app import Cosmos  # noqa: E402
from cosmos_tui.app import TerminalSurface  # noqa: E402
from cosmos_tui.render.graphics import Batch  # noqa: E402


class Probe(Cosmos):
    async def on_mount(self, event):
        event.prevent_default()
        self._workspace_screen = self.screen

    async def on_unmount(self, event):
        event.prevent_default()


class RenderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_mod_popup_uses_folded_frame_without_overrunning_rect(self):
        app = Probe()
        async with app.run_test(size=(80, 24)):
            app.views = [
                {
                    "view": {
                        "kind": "help",
                        "content": {
                            "title": "Mod preview",
                            "lines": [{"text": "Body", "role": "fg"}],
                        },
                    },
                    "rect": {"x": 2, "y": 1, "width": 30, "height": 6},
                }
            ]
            surface = app.query_one(TerminalSurface)
            top = surface.render_line(1)
            self.assertIn("╭─┐ Mod preview ┌", top.text)
            body = surface.render_line(2).text
            self.assertEqual(body[2], "│")
            self.assertEqual(body[31], "│")
            self.assertIn("Body", body)
            self.assertEqual(top.cell_length, 80)
            self.assertEqual(surface.render_line(6).text[2], "╰")

    async def test_suppressed_batch_preserves_packet_for_later_display(self):
        app = Probe()
        async with app.run_test():
            app.graphics.pending = "queued-image"
            old = app._batch_count
            app._batch_count = old + 1
            try:
                app._display(app.screen, Batch())
                self.assertEqual(app.graphics.pending, "queued-image")
            finally:
                app._batch_count = old


if __name__ == "__main__":
    unittest.main()


class GraphicsDetectionTests(unittest.TestCase):
    def test_ghostty_graphics_and_explicit_text_override(self):
        from cosmos_tui.render.graphics import Graphics

        with patch.dict(os.environ, {"TERM": "xterm-ghostty", "COSMOS_GRAPHICS": ""}):
            self.assertTrue(Graphics().enabled)
        with patch.dict(
            os.environ, {"TERM": "xterm-ghostty", "COSMOS_GRAPHICS": "text"}
        ):
            self.assertFalse(Graphics().enabled)
