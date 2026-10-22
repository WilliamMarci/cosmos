"""Boundary checks for the real UI, shell routing and terminal color contracts."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / name)
    for name in ("python", "terminal_agent")
]
from cosmos_tui.ui import Rect, boundaries, cell_width, snap  # noqa: E402
from cosmos_tui.island import layout_island  # noqa: E402
from cosmos_tui.backend import Pane  # noqa: E402
from cosmos_tui.terminal_grid import decode_grid  # noqa: E402
from cosmos_tui.open_file import main as open_file  # noqa: E402
from cosmos_tui import keymap  # noqa: E402


class Interfaces(unittest.TestCase):
    def test_safe_island_widths_actions_and_no_command_overlap(self):
        for width in (88, 40, 24, 12, 4):
            pane = Pane("%1", 0, 0, width, 20, True, [], "", (1, 5))
            command = Rect(
                0, 2, width, 6
            )  # cursor may be in the middle of a wrapped command
            for expanded in (False, True):
                layout = layout_island(pane, command, "中文e\u0301" * 50, expanded)
                self.assertIsNotNone(layout)
                self.assertEqual(layout.bounds.width, width)
                self.assertEqual(layout.bounds.x, pane.x)
                if layout.status:
                    self.assertEqual(layout.status.x, pane.x + 1)
                    self.assertEqual(layout.editor.x, pane.x + 3)
                self.assertLessEqual(layout.bounds.x + layout.bounds.width, width)
                self.assertFalse(layout.bounds.intersects(command))
                self.assertEqual(bool(layout.actions), expanded and layout.can_expand)
                if layout.actions:
                    self.assertGreaterEqual(layout.editor.width, 12)
                    self.assertEqual(
                        layout.editor.x + layout.editor.width, layout.actions[0][1].x
                    )
                    for (_, left), (_, right) in zip(
                        layout.actions, layout.actions[1:]
                    ):
                        self.assertEqual(left.x + left.width, right.x)
        pane = Pane("%1", 0, 0, 20, 4, True, [], "", (1, 1))
        self.assertIsNone(layout_island(pane, Rect(0, 0, 20, 4), "request"))

    def test_grapheme_cursor_boundaries(self):
        text = "中e\u0301👩\u200d💻"
        self.assertEqual(boundaries(text), [0, 1, 3, 6])
        self.assertEqual(snap(text, 2), 1)
        self.assertEqual(cell_width(text), 5)

    def test_pane_ansi_color_survives_line_boundary_and_reset(self):
        rows = decode_grid(("\x1b[48;2;12;34;56mfirst", "second", "\x1b[0mthird"))
        self.assertEqual(rows[1].spans[0].style.bgcolor.triplet, (12, 34, 56))
        self.assertFalse(rows[2].spans)

    def test_open_dispatch_keeps_filenames_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "-some photo.PNG"
            image.touch()
            other = Path(tmp) / "readme.txt"
            other.touch()
            with (
                patch.dict(
                    os.environ,
                    {
                        "TMUX": "socket,1,0",
                        "TMUX_PANE": "%1",
                        "COSMOS_BINARY": "/cosmos",
                    },
                ),
                patch("cosmos_tui.open_file.subprocess.call", return_value=0) as call,
            ):
                self.assertEqual(
                    open_file(["--", str(image), str(other), "https://example.com"]), 0
                )
                self.assertEqual(
                    call.call_args_list[0].args[0], ["/cosmos", "open", str(image)]
                )
                self.assertEqual(
                    call.call_args_list[1].args[0], ["xdg-open", str(other)]
                )
                self.assertEqual(
                    call.call_args_list[2].args[0], ["xdg-open", "https://example.com"]
                )

    def test_remapped_binding_dispatch_and_help_share_registry(self):
        settings = {"keybindings": {"workspace.split_vertical": ["leader+v"]}}
        keymap.validate(settings["keybindings"])
        self.assertIsNone(
            keymap.resolve("workspace", "leader+quotation_mark", settings)
        )
        command = keymap.resolve("workspace", "leader+v", settings)
        self.assertEqual(command.target, "quotation_mark")
        self.assertIn(
            ("Leader v", "Split top / bottom"), keymap.help_rows("workspace", settings)
        )
        with self.assertRaises(ValueError):
            keymap.validate({"workspace.split_vertical": ["leader+p"]})


if __name__ == "__main__":
    unittest.main()
