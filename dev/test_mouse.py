"""Client-local mouse negotiation and real SGR decoding, without a daemon."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / p) for p in ("python", "terminal_agent")
]
from cosmos_tui.terminal.mouse import CosmosLinuxDriver, MouseParser  # noqa: E402
from test_navigation import Probe  # noqa: E402
from cosmos_tui.features.settings.panel import Palette  # noqa: E402
from textual.widgets import ListView  # noqa: E402


def driver(mode):
    value = object.__new__(CosmosLinuxDriver)
    value._app = Mock(mouse_mode=mode)
    value._mouse = True
    value._debug = False
    value.write, value.flush = Mock(), Mock()
    value.pixel_supported = False
    value.effective_mouse_mode = "cell"
    value.mouse_parser = MouseParser(value)
    value.mouse_parser.terminal_size = (80, 24)
    value.mouse_parser.terminal_pixel_size = (800, 480)
    return value


class MouseTests(unittest.TestCase):
    def test_cli_mouse_mode_reaches_client_for_all_attach_spellings(self):
        from cosmos_tui.core.cli import main

        for arguments in (
            ["--mouse-mode", "cell"],
            ["--mouse-mode=cell", "project"],
            ["attach", "project", "--mouse-mode", "cell"],
            ["session", "attach", "project", "--mouse-mode", "cell"],
            ["--mouse-mode", "cell", "session", "attach", "project"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch("cosmos_tui.runtime.bootstrap.run") as run,
            ):
                main(arguments)
                self.assertEqual(run.call_args.args[0].mouse_mode, "cell")

    def test_probe_and_cell_override_use_matching_parser_coordinates(self):
        value = driver("auto")
        value.apply_mouse_mode()
        self.assertEqual(value.effective_mouse_mode, "cell")
        list(value.mouse_parser.feed("\x1b[?1016;"))
        list(value.mouse_parser.feed("2$y"))
        self.assertEqual(value.effective_mouse_mode, "pixel")
        event = value.mouse_parser.parse_mouse_code("\x1b[<0;101;101M")
        self.assertEqual((event.x, event.y), (10, 5))
        value._app.mouse_mode = "cell"
        value.apply_mouse_mode()
        # Even when Textual sees a later in-band resize, Cell must win.
        value.mouse_parser.mouse_pixels = True
        event = value.mouse_parser.parse_mouse_code("\x1b[<0;11;6M")
        self.assertEqual((event.x, event.y), (10, 5))
        self.assertEqual(value.effective_mouse_mode, "cell")
        self.assertIn(
            "\x1b[?1016l\x1b[?1006h", [c.args[0] for c in value.write.call_args_list]
        )

    def test_explicit_pixel_needs_geometry_and_cleanup_disables_it(self):
        value = driver("pixel")
        value.apply_mouse_mode()
        self.assertEqual(value.effective_mouse_mode, "pixel")
        value.mouse_parser.terminal_pixel_size = None
        value.apply_mouse_mode()
        self.assertEqual(value.effective_mouse_mode, "cell")
        value._disable_mouse_support()
        self.assertIn("\x1b[?1016l", [c.args[0] for c in value.write.call_args_list])


class MouseUITests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_affect_only_current_client_without_settings_rpc(self):
        first, second = Probe(), Probe()
        snapshot = dict(actions=[], settings={})
        with patch(
            "cosmos_tui.features.settings.panel.rpc.call", return_value=snapshot
        ) as rpc:
            async with first.run_test(size=(80, 24)) as pilot:
                first.push_screen(Palette("input_settings"))
                await pilot.pause()
                self.assertEqual(first.screen.rows[0]["label"], "Mouse mode")
                await first.screen.invoke()
                first.screen.query_one(ListView).index = 1
                await first.screen.invoke()
                self.assertEqual(first.mouse_mode, "cell")
                self.assertEqual(second.mouse_mode, "auto")
                self.assertNotIn(
                    "settings.replace", [c.args[0] for c in rpc.call_args_list]
                )
                with patch.dict(os.environ, {"COSMOS_GRAPHICS": "kitty"}):
                    self.assertEqual(first.mouse_mode, "cell")
