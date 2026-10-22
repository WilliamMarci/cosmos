"""Headless focus/selection regressions; the PTY smoke covers real backend changes."""

import asyncio
import sys
import unittest
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "terminal_agent"))
from textual import events  # noqa: E402
from textual.widgets import Input, ListView  # noqa: E402
from cosmos_tui.app import Cosmos  # noqa: E402
from cosmos_tui.features.navigation.switcher import Switcher, LayoutPreview  # noqa: E402


class Backend:
    tabs = [["@0", "0", "1", "shell"]]

    def __init__(self):
        self.selected = None

    async def inventory(self):
        await asyncio.sleep(0.03)
        return [
            dict(
                session_id="$0", session="main", window_id="@0", index="0", name="shell"
            ),
            dict(
                session_id="$1",
                session="other",
                window_id="@1",
                index="0",
                name="target",
            ),
        ]

    async def snapshot(self, window=None):
        return []

    async def select_window(self, window):
        self.selected = window


class Probe(Cosmos):
    async def on_mount(self, event):
        event.prevent_default()
        self._workspace_screen = self.screen
        self.backend = Backend()

    async def on_unmount(self, event):
        event.prevent_default()


class SwitcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_filter_keeps_focus_and_confirmation_uses_latest_query(self):
        app = Probe()
        async with app.run_test() as pilot:
            await pilot.press("ctrl+b", "s")
            await pilot.pause()
            self.assertIsInstance(app.screen, Switcher)
            app.screen.query_one(ListView).focus()
            await pilot.pause()
            self.assertIs(app.focused, app.screen.query_one(Input))
            # A real driver may enqueue an entire read before the focus callbacks run.
            app.screen.set_focus(None)
            for character in "target":
                app.post_message(events.Key(character, character))
            app.post_message(events.Key("enter", "\r"))
            await pilot.pause()
            self.assertEqual(app.backend.selected["window_id"], "@1")
            self.assertIs(app.screen, app._workspace_screen)

    async def test_confirm_waits_for_inventory_and_ignores_stale_list_selection(self):
        app = Probe()
        async with app.run_test() as pilot:
            await pilot.press("ctrl+b", "s")
            await pilot.pause()
            screen = app.screen
            screen.inventory_ready.clear()
            screen.query_one(Input).value = "target"
            screen.query_one(ListView).index = None
            confirmation = asyncio.create_task(screen.confirm())
            await asyncio.sleep(0)
            self.assertFalse(confirmation.done())
            screen.inventory_ready.set()
            await confirmation
            self.assertEqual(app.backend.selected["window_id"], "@1")

    async def test_list_left_preview_right_with_outer_frame(self):
        app = Probe()
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press("ctrl+b", "s")
            await pilot.pause()
            listing = app.screen.query_one("#switch-browser")
            preview = app.screen.query_one(LayoutPreview)
            self.assertLessEqual(listing.region.right, preview.region.x)
            self.assertEqual(listing.region.y, preview.region.y)
            self.assertGreater(preview.region.width, listing.region.width)
            self.assertEqual(
                app.screen.query_one("#switcher").styles.border_top[0], "round"
            )
            frame = app.screen.query_one("#switcher")
            divider = app.screen.query_one("#switch-divider")
            x = divider.region.x - frame.region.x
            self.assertEqual(frame.border_strip(True).text[x], "┬")
            self.assertEqual(frame.border_strip(False).text[x], "┴")
            self.assertEqual(divider.region.y, frame.region.y + 1)
            self.assertEqual(divider.region.bottom, frame.region.bottom - 1)
            self.assertIn("┐ Switch ┌", frame.border_strip(True).text)
            heading = frame.heading(app.role_colors)
            self.assertTrue(any(s.start == 0 and s.end == 1 for s in heading.spans))
            app.settings["keybindings"] = {"workspace.switch": ["leader+w"]}
            heading = frame.heading(app.role_colors)
            self.assertTrue(any(s.start == 1 and s.end == 2 for s in heading.spans))

    async def test_slow_preview_never_activates_textual_loading_cover(self):
        app = Probe()
        async with app.run_test() as pilot:
            started = asyncio.Event()
            finish = asyncio.Event()

            async def slow_snapshot(window=None):
                started.set()
                await finish.wait()
                return []

            app.backend.snapshot = slow_snapshot
            await pilot.press("ctrl+b", "s")
            await asyncio.wait_for(started.wait(), 1)
            try:
                self.assertTrue(app.screen.preview_busy)
                self.assertFalse(app.screen.loading)
                await pilot.press(*"target")
                self.assertEqual(app.screen.query_one(Input).value, "target")
                self.assertFalse(app.screen.loading)
            finally:
                finish.set()
            await pilot.pause()

    async def test_cancel_and_help_do_not_switch(self):
        app = Probe()
        async with app.run_test() as pilot:
            await pilot.press("ctrl+b", "s")
            await pilot.pause()
            await pilot.press("ctrl+b", "question_mark")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, Switcher)
            self.assertIs(app.focused, app.screen.query_one(Input))
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsNone(app.backend.selected)
            self.assertIs(app.screen, app._workspace_screen)


if __name__ == "__main__":
    unittest.main()
