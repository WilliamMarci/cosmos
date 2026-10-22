"""Leader dispatch must precede focus widgets and normalize punctuation."""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch, Mock

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / n) for n in ("python", "terminal_agent")
]
from textual import events  # noqa: E402
from cosmos_tui.app import Cosmos  # noqa: E402
from textual._xterm_parser import XTermParser  # noqa: E402
from cosmos_tui.backend import Pane  # noqa: E402


class ShortcutTests(unittest.IsolatedAsyncioTestCase):
    async def test_shifted_quote_character_and_named_key_dispatch(self):
        for key, character in [
            ("quotation_mark", '"'),
            ("shift+apostrophe", '"'),
            ("quotation_mark", None),
        ]:
            app = Cosmos("test")
            app.action_leader_key = AsyncMock()
            await app.on_event(events.Key("ctrl+b", "\x02"))
            self.assertTrue(app.prefix)
            await app.on_event(events.Key(key, character))
            app.action_leader_key.assert_awaited_once_with("quotation_mark")

    async def test_modifier_presses_preserve_leader_with_real_kitty_sequences(self):
        parser = XTermParser(lambda: False)
        for shift in (57441, 57447):
            app = Cosmos("test")
            app.action_leader_key = AsyncMock()
            await app.on_event(events.Key("ctrl+b", "\x02"))
            for sequence in (f"\x1b[{shift}u", "\x1b[39;2;34u"):
                for event in parser._parse_extended_key(sequence):
                    await app.on_event(event)
            app.action_leader_key.assert_awaited_once_with("quotation_mark")

    async def test_shift_without_associated_text_and_lock_key(self):
        for key, expected in [
            ("shift+apostrophe", "quotation_mark"),
            ("shift+5", "percent_sign"),
            ("shift+h", "H"),
        ]:
            app = Cosmos("test")
            app.action_leader_key = AsyncMock()
            await app.on_event(events.Key("ctrl+b", "\x02"))
            await app.on_event(events.Key("caps_lock", None))
            self.assertTrue(app.prefix)
            await app.on_event(events.Key(key, None))
            app.action_leader_key.assert_awaited_once_with(expected)

    async def test_nonexistent_window_notifies_and_keeps_ui_alive(self):
        class Probe(Cosmos):
            async def on_mount(self, event):
                event.prevent_default()
                self._workspace_screen = self.screen
                self.panes = [Pane("%0", 0, 0, 80, 23, True, [], "", (0, 0))]
                self.backend = Mock(
                    request=AsyncMock(side_effect=RuntimeError("can't find window: 5"))
                )

            async def on_unmount(self, event):
                event.prevent_default()

        app = Probe("test")
        with patch("cosmos_tui.app.rpc.call", AsyncMock()) as rpc:
            async with app.run_test() as pilot:
                await pilot.press("ctrl+b", "5")
                await pilot.pause()
                self.assertTrue(app.is_running)
                self.assertFalse(app.prefix)
                rpc.assert_awaited_once()
                self.assertIn("can't find window: 5", rpc.call_args.args[1]["text"])


if __name__ == "__main__":
    unittest.main()
