# ruff: noqa: E402
"""IME display contract and bounded shortcut help layout."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe
from cosmos_tui.features.ime.layout import compose
from cosmos_tui.ui.cells import Rect
from cosmos_tui.ui.styles import DARK
from cosmos_tui.ui.help import Help
from cosmos_tui.ui.keyboard import KeyboardPreview, key_phases
from textual.widgets import ListView


class IMELayoutTests(unittest.TestCase):
    def test_editable_caret_segments_number_style_and_page_limits(self):
        context = dict(
            preedit="ni hao",
            cursor=2,
            selection=(0, 2),
            candidates=["你好", "拟好"],
            selected=0,
            page=0,
            last_page=False,
        )
        frame = compose(context, Rect(0, 0, 40, 10), (3, 2), DARK, "superscript")
        caret = next(r for r in frame.runs if r.reverse)
        self.assertEqual(caret.rect.x, frame.bounds.x + 2)
        self.assertTrue(any(r.underline for r in frame.runs))
        self.assertTrue(
            any("¹" in r.text and r.foreground == "yellow" for r in frame.runs)
        )
        self.assertFalse(next(h for h in frame.hits if h.action == "pageup").enabled)
        self.assertTrue(next(h for h in frame.hits if h.action == "pagedown").enabled)
        context.update(cursor=1, page=1, last_page=True)
        frame = compose(context, Rect(0, 0, 40, 10), (3, 2), DARK, "subscript")
        self.assertTrue(any("₁" in r.text for r in frame.runs))
        self.assertFalse(next(h for h in frame.hits if h.action == "pagedown").enabled)
        first, second = key_phases(["ctrl+m x"])
        self.assertEqual(first, {"Ctrl", "M"})
        self.assertEqual(second, {"X"})


class HelpLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_help_scrolls_above_visible_keyboard(self):
        app = Probe()
        async with app.run_test(size=(90, 28)) as pilot:
            app.push_screen(
                Help("Shortcuts", [(f"Leader {i}", f"Action {i}") for i in range(80)])
            )
            await pilot.pause()
            keyboard = app.screen.query_one(KeyboardPreview)
            listing = app.screen.query_one(ListView)
            self.assertTrue(keyboard.display)
            self.assertLess(listing.region.height, 80)
            await pilot.press("end")
            await pilot.pause()
            self.assertEqual(listing.index, 79)
            self.assertGreater(listing.scroll_y, 0)
            self.assertEqual(app.screen.query_one("#key-legend").region.height, 1)
