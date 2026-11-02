"""Captured tabs occupy pane-local display columns before compositing."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest

from rich.console import Console
from rich.segment import Segment
from textual.strip import Strip

from cosmos_tui.render.ansi import decode_grid


class TerminalTabsTests(unittest.TestCase):
    def test_tabs_expand_by_display_cells_and_keep_sgr_across_rows(self):
        rows = decode_grid(("\x1b[41m中\tB", "e\u0301\tC", "12345678\tD\x1b[0m", "plain"))
        self.assertEqual([row.plain for row in rows], ["中      B", "e\u0301       C", "12345678        D", "plain"])
        self.assertEqual([row.cell_len for row in rows], [9, 9, 17, 5])
        console = Console()
        self.assertEqual(rows[0].get_style_at_offset(console, 3).bgcolor.name, "color(1)")
        self.assertEqual(rows[1].get_style_at_offset(console, 3).bgcolor.name, "color(1)")
        self.assertFalse(rows[3].spans)

    def test_cropped_left_pane_cannot_send_tab_into_right_border(self):
        console = Console()
        for prefix in ("A", "中", "e\u0301"):
            text = decode_grid((prefix + "\tB",))[0]
            strip = Strip(text.render(console, end="")).crop(0, 5).extend_cell_length(5)
            combined = Strip.join([strip, Strip([Segment("│RIGHT")])])
            self.assertNotIn("\t", combined.text)
            self.assertEqual(combined.cell_length, 11)
            self.assertEqual(Strip(combined).crop(5, 6).text, "│")


@unittest.skipUnless(os.getenv("COSMOS_TEST_TMUX"), "requires isolated Tmux server")
class RealTmuxTabsTests(unittest.TestCase):
    def test_actual_capture_tabs_are_expanded_before_render(self):
        with tempfile.TemporaryDirectory(prefix="cosmos-tab-test-") as folder:
            command = ["/usr/bin/tmux", "-S", folder + "/socket", "-f", "/dev/null"]
            env = dict(PATH="/usr/bin:/bin", TERM="xterm-256color", HOME=folder, LC_ALL="C.UTF-8")
            fixture = Path(folder) / "emit.py"
            fixture.write_text("import os,time\nos.write(1, b'A\\tB\\r\\n\\x1b[31mC\\tEND\\x1b[0m\\r\\n');time.sleep(30)\n")
            def call(*args):
                return subprocess.check_output(command + list(args), env=env, timeout=4)
            try:
                call("new-session", "-d", "-x", "40", "-y", "8", shlex.join([sys.executable, str(fixture)]))
                capture = b""
                for _ in range(20):
                    capture = call("capture-pane", "-p", "-e", "-C", "-N", "-t", "%0")
                    if b"END" in capture:
                        break
                    time.sleep(0.05)
                self.assertIn(b"END", capture)
                self.assertIn(b"\t", capture)
                # Match snapshot's -C octal/backslash transport decoding.
                lines = tuple(re.sub(
                    r"\\([0-7]{3}|\\)",
                    lambda m: chr(int(m[1], 8)) if m[1] != "\\" else "\\",
                    line,
                ) for line in capture.decode().splitlines())
                rows = decode_grid(lines)
                self.assertEqual(rows[0].plain.rstrip(), "A       B")
                self.assertEqual(rows[1].plain.rstrip(), "C       END")
                self.assertTrue(all("\t" not in row.plain for row in rows))
            finally:
                subprocess.run(command + ["kill-server"], env=env, timeout=4, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class AgentTabCoordinatesTests(unittest.IsolatedAsyncioTestCase):
    async def test_observed_button_and_mouse_packet_use_same_display_column(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from cosmos_tui.features.agent.observation.snapshot import build
        from cosmos_tui.features.agent.terminal import TerminalTools

        row = dict(pane_id="%19", pane_width=40, pane_height=2, cursor_x=0, cursor_y=0,
                   pane_current_command="fixture", pane_in_mode=False, alternate_on=False,
                   mouse_any_flag=True, mouse_button_flag=True, mouse_all_flag=False,
                   mouse_utf8_flag=False, mouse_sgr_flag=True)
        for prefix in ("A", "中", "e\u0301"):
            raw = prefix + "\t\x1b[32m[OK]\x1b[0m"
            result = build(row, raw, ["text", "presentation", "controls"])
            button = result["controls"][0]["region"]
            self.assertEqual(button, dict(x=9, y=1, width=4, height=1))
            self.assertNotIn("\t", result["text"][0]["text"])
            cropped = build(row, raw, ["text", "controls"], dict(x=9, y=1, width=4, height=1))
            self.assertEqual(cropped["text"][0]["text"], "[OK]")
            self.assertEqual(cropped["controls"][0]["region"], button)
            tools = SimpleNamespace(pane=AsyncMock(return_value=row), _prepare_input=AsyncMock(return_value=False), backend=SimpleNamespace(argv=["tmux", "-L", "fixture"], cli=AsyncMock()))
            with patch("cosmos_tui.features.agent.control.ControlStore"):
                await TerminalTools._mouse(tools, "%19", button["x"], button["y"])
            args = tools.backend.cli.call_args.args
            self.assertEqual(args[:4], ("send-keys", "-H", "-t", "%19"))
            packet = bytes(int(value, 16) for value in args[4:])
            self.assertEqual(packet, b"\x1b[<0;9;1M\x1b[<0;9;1m")
