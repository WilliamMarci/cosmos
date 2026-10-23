"""Client-local mouse negotiation and real SGR decoding, without a daemon."""

import asyncio
import os
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / p) for p in ("python", "terminal_agent")
]
from cosmos_tui.input import mouse_protocol  # noqa: E402
from cosmos_tui.terminal.mouse import CosmosLinuxDriver, MouseParser  # noqa: E402
from cosmos_tui.terminal.tmux import Pane, Tmux  # noqa: E402
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


def pointer(x=5, y=6, button=0, shift=False, meta=False, ctrl=False):
    return SimpleNamespace(
        screen_x=x,
        screen_y=y,
        button=button,
        shift=shift,
        meta=meta,
        ctrl=ctrl,
        stop=Mock(),
    )


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

    def test_application_mouse_protocols(self):
        pane = Pane(
            "%0",
            0,
            0,
            80,
            23,
            True,
            [],
            "",
            (0, 0),
            mouse_any=True,
            mouse_button=True,
            mouse_sgr=True,
        )
        self.assertEqual(
            mouse_protocol.encode(pane, 0, 5, 6), b"\x1b[<0;5;6M"
        )
        self.assertEqual(
            mouse_protocol.encode(pane, 0, 5, 6, release=True), b"\x1b[<0;5;6m"
        )
        self.assertEqual(
            mouse_protocol.encode(pane, 0, 5, 6, motion=True),
            b"\x1b[<32;5;6M",
        )
        self.assertEqual(
            mouse_protocol.encode(
                pane, 0, 5, 6, modifier_bits=mouse_protocol.SHIFT
            ),
            b"\x1b[<4;5;6M",
        )
        self.assertEqual(
            mouse_protocol.encode(pane, mouse_protocol.WHEEL_UP, 5, 6),
            b"\x1b[<64;5;6M",
        )
        pane.mouse_sgr = False
        pane.mouse_standard = True
        pane.mouse_button = False
        self.assertEqual(
            mouse_protocol.encode(pane, 0, 5, 6), b"\x1b[M %&"
        )
        self.assertEqual(
            mouse_protocol.encode(pane, 0, 5, 6, release=True), b"\x1b[M#%&"
        )
        self.assertIsNone(
            mouse_protocol.encode(pane, 0, 5, 6, motion=True)
        )
        pane.mouse_utf8 = True
        self.assertEqual(
            mouse_protocol.encode(pane, 0, 200, 201),
            b"\x1b[M \xc3\xa8\xc3\xa9",
        )

class MouseUITests(unittest.IsolatedAsyncioTestCase):
    async def test_send_bytes_uses_literal_tmux_injection(self):
        backend = object.__new__(Tmux)
        backend.request = AsyncMock()
        await backend.send_bytes("%2", b"\x1b[<0;1;1M")
        backend.request.assert_awaited_once_with(
            "send-keys -H -t %2 1b 5b 3c 30 3b 31 3b 31 4d"
        )
        with self.assertRaises(ValueError):
            await backend.send_bytes("2", b"x")
        with self.assertRaises(ValueError):
            await backend.send_bytes("%2", b"")

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
                first.screen.query_one(ListView).index = 0
                await first.screen.invoke()
                self.assertEqual(first.mouse_mode, "cell")
                self.assertEqual(second.mouse_mode, "auto")
                self.assertNotIn(
                    "settings.replace", [c.args[0] for c in rpc.call_args_list]
                )
                with patch.dict(os.environ, {"COSMOS_GRAPHICS": "kitty"}):
                    self.assertEqual(first.mouse_mode, "cell")

    async def test_mouse_passthrough_setting_is_shared(self):
        state = dict(actions=[], settings={"mouse_passthrough": True})

        async def rpc(method, params=None):
            if method == "state.snapshot":
                return state
            if method == "settings.get":
                return dict(state["settings"])
            if method == "settings.replace":
                state["settings"] = dict(params)
                return {}
            return []

        app = Probe()
        app.settings["mouse_passthrough"] = True
        with patch("cosmos_tui.core.rpc.call", side_effect=rpc):
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(Palette("input_settings"))
                await pilot.pause()
                menu = app.screen
                menu.query_one(ListView).index = next(
                    i
                    for i, row in enumerate(menu.rows)
                    if row["label"] == "Mouse passthrough"
                )
                await pilot.press("right")
                self.assertFalse(state["settings"]["mouse_passthrough"])
                self.assertFalse(app.settings["mouse_passthrough"])
                await pilot.press("left")
                self.assertTrue(state["settings"]["mouse_passthrough"])
                self.assertTrue(app.settings["mouse_passthrough"])

    async def test_pointer_forwards_and_falls_back_to_history(self):
        app = Probe()
        async with app.run_test(size=(80, 24)):
            app.settings["mouse_passthrough"] = True
            app.panes = [
                Pane(
                    "%0",
                    0,
                    0,
                    80,
                    23,
                    True,
                    [],
                    "",
                    (0, 0),
                    mouse_any=True,
                    mouse_button=True,
                    mouse_sgr=True,
                )
            ]
            app.backend.send_bytes = AsyncMock()

            await app.pointer.on_mouse_scroll_up(pointer())
            app.backend.send_bytes.assert_awaited_once_with(
                "%0", b"\x1b[<64;6;7M"
            )
            app.backend.request.assert_not_awaited()

            app.backend.send_bytes.reset_mock()
            await app.pointer.on_mouse_down(pointer(x=4, y=3, button=1))
            app.backend.send_bytes.assert_awaited_once_with(
                "%0", b"\x1b[<0;5;4M"
            )
            self.assertEqual(app.pointer.press, ("%0", 0))
            app.backend.send_bytes.reset_mock()
            await app.pointer.on_mouse_move(pointer(x=6, y=5, button=1))
            app.backend.send_bytes.assert_awaited_once_with(
                "%0", b"\x1b[<32;7;6M"
            )
            app.backend.send_bytes.reset_mock()
            await app.pointer.on_mouse_up(pointer(x=6, y=5, button=1))
            app.backend.send_bytes.assert_awaited_once_with(
                "%0", b"\x1b[<0;7;6m"
            )
            self.assertIsNone(app.pointer.press)

            app.settings["mouse_passthrough"] = False
            app.backend.send_bytes.reset_mock()
            app.backend.request.reset_mock()
            await app.pointer.on_mouse_scroll_up(pointer())
            app.backend.send_bytes.assert_not_awaited()
            self.assertIn(
                "copy-mode -t %0",
                [call.args[0] for call in app.backend.request.await_args_list],
            )

            app.settings["mouse_passthrough"] = True
            app.active().mouse_any = False
            app.backend.send_bytes.reset_mock()
            app.backend.request.reset_mock()
            await app.pointer.on_mouse_scroll_up(pointer())
            app.backend.send_bytes.assert_not_awaited()
            self.assertIn(
                "copy-mode -t %0",
                [call.args[0] for call in app.backend.request.await_args_list],
            )

    async def test_mouse_passthrough_action_toggles_shared_setting(self):
        state = {"mouse_passthrough": True}

        async def rpc(method, params=None):
            if method == "settings.get":
                return dict(state)
            if method == "settings.replace":
                state.update(params)
                return {}
            return []

        app = Probe()
        app.settings.update(state)
        with patch("cosmos_tui.core.rpc.call", side_effect=rpc):
            await app.action_leader_key("mouse_passthrough")
            self.assertFalse(state["mouse_passthrough"])
            self.assertFalse(app.settings["mouse_passthrough"])
            await app.action_leader_key("mouse_passthrough")
            self.assertTrue(state["mouse_passthrough"])
            self.assertTrue(app.settings["mouse_passthrough"])


@unittest.skipUnless(
    os.getenv("COSMOS_TEST_TMUX") == "1", "requires an isolated local Tmux socket"
)
class MousePassthroughTmuxTests(unittest.IsolatedAsyncioTestCase):
    async def test_pane_flags_and_raw_reports(self):
        code = "\n".join(
            [
                "import os, select, sys, time, tty",
                "sys.stdout.write('\\033[?1002h\\033[?1006h')",
                "sys.stdout.flush()",
                "tty.setraw(0)",
                "data = b''",
                "end = time.time() + 10",
                "while time.time() < end:",
                "    ready, _, _ = select.select([0], [], [], 0.05)",
                "    if ready:",
                "        data += os.read(0, 64)",
                "        if b'M' in data or b'm' in data:",
                "            break",
                "print(data.hex(), flush=True)",
                "time.sleep(10)",
            ]
        )
        with patch.dict(
            os.environ, {"COSMOS_TMUX_SOCKET": f"cosmos-mouse-test-{os.getpid()}"}
        ):
            backend = Tmux("mouse")
            await backend.cli(
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-s",
                "mouse",
                shlex.join(["python3", "-c", code]),
            )
            try:
                await backend.connect()
                pane = None
                for _ in range(30):
                    pane = (await backend.snapshot())[0]
                    if pane.mouse_any:
                        break
                    await asyncio.sleep(0.1)
                self.assertTrue(pane.mouse_any)
                self.assertTrue(pane.mouse_button)
                self.assertTrue(pane.mouse_sgr)
                await backend.send_bytes(pane.id, b"\x1b[<0;3;4M")
                expected = b"\x1b[<0;3;4M".hex()
                output = ""
                for _ in range(30):
                    output = await backend.cli(
                        "capture-pane", "-p", "-t", pane.id
                    )
                    if expected in output:
                        break
                    await asyncio.sleep(0.1)
                self.assertIn(expected, output)
            finally:
                await backend.close()
                try:
                    await backend.cli("kill-server")
                except RuntimeError:
                    pass
