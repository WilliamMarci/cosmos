"""A suppressed Textual display batch must not discard queued Kitty images."""

import sys
import unittest
from pathlib import Path

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / n) for n in ("python", "terminal_agent")
]
from cosmos_tui.app import Cosmos  # noqa: E402
from cosmos_tui.rendering import Batch  # noqa: E402


class Probe(Cosmos):
    async def on_mount(self, event):
        event.prevent_default()
        self._workspace_screen = self.screen

    async def on_unmount(self, event):
        event.prevent_default()


class RenderingTests(unittest.IsolatedAsyncioTestCase):
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
