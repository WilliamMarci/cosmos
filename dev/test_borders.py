"""Pane gutters preserve Tmux geometry and join unequal split layouts."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from cosmos_tui.borders import borders  # noqa: E402


class BorderTests(unittest.TestCase):
    def test_three_panes_tee_and_active_edges(self):
        layout = ((0, 0, 80, 10, False), (0, 11, 39, 12, True), (40, 11, 40, 12, False))
        rows = borders(80, 23, layout)
        self.assertEqual(rows[10][39], ("┬", True))
        self.assertEqual(rows[10][5], ("─", True))
        self.assertEqual(rows[10][60], ("─", False))
        self.assertEqual(rows[22][39], ("│", True))
        self.assertEqual(len(rows[10]), 80)
        for y, row in rows.items():
            for x in row:
                self.assertFalse(
                    any(
                        px <= x < px + w and py <= y < py + h
                        for px, py, w, h, _ in layout
                    )
                )

    def test_four_panes_cross_and_focus_change(self):
        layout = (
            (0, 0, 39, 11, True),
            (40, 0, 40, 11, False),
            (0, 12, 39, 11, False),
            (40, 12, 40, 11, False),
        )
        self.assertEqual(borders(80, 23, layout)[11][39], ("┼", True))
        moved = tuple((*p[:4], index == 3) for index, p in enumerate(layout))
        self.assertEqual(borders(80, 23, moved)[0][39], ("│", False))
        self.assertEqual(borders(80, 23, moved)[22][39], ("│", True))

    def test_two_panes_half_highlight_matches_tmux(self):
        left = ((0, 0, 39, 23, True), (40, 0, 40, 23, False))
        self.assertTrue(borders(80, 23, left)[11][39][1])
        self.assertFalse(borders(80, 23, left)[12][39][1])
        right = tuple((*p[:4], not p[4]) for p in left)
        self.assertFalse(borders(80, 23, right)[11][39][1])
        self.assertTrue(borders(80, 23, right)[12][39][1])
        top = ((0, 0, 80, 11, True), (0, 12, 80, 11, False))
        self.assertTrue(borders(80, 23, top)[11][40][1])
        self.assertFalse(borders(80, 23, top)[11][41][1])
        bottom = tuple((*p[:4], not p[4]) for p in top)
        self.assertFalse(borders(80, 23, bottom)[11][40][1])
        self.assertTrue(borders(80, 23, bottom)[11][41][1])

    def test_single_or_zoomed_pane_has_no_frame(self):
        self.assertEqual(borders(80, 23, ((0, 0, 80, 23, True),)), {})


if __name__ == "__main__":
    unittest.main()
