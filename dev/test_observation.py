"""Layer selection, Unicode cell geometry and conservative capability claims."""

import unittest

from cosmos_tui.features.agent.observation.snapshot import Observations, build


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(
            pane_id="%7",
            pane_width=40,
            pane_height=4,
            cursor_x=0,
            cursor_y=0,
            pane_current_command="fixture",
        )

    def test_styled_unicode_region_and_inferred_controls(self):
        result = build(
            self.row,
            "\x1b[31m中文 [ OK ]\x1b[0m\nbody",
            ["text", "presentation", "controls"],
        )
        self.assertEqual(result["controls"][0]["region"]["x"], 6)
        self.assertEqual(result["controls"][0]["source"], "terminal_inference")
        self.assertEqual(result["controls"][0]["actions"], [])
        self.assertFalse(result["capabilities"]["act"])
        self.assertTrue(
            any(
                "color(1)" in span["style"]
                for span in result["presentation"]["rows"][0]["spans"]
            )
        )
        cropped = build(
            self.row, "中文 [ OK ]\nbody", ["text"], dict(x=6, y=1, width=6, height=1)
        )
        self.assertEqual(cropped["text"][0]["text"], "[ OK ]")
        self.assertNotIn("presentation", cropped)
        self.assertNotIn("controls", cropped)
        with self.assertRaises(ValueError):
            build(self.row, "x", ["text"], dict(x=40, y=1, width=2, height=1))

    def test_region_snapshot_ignores_changes_outside_region(self):
        region = dict(x=1, y=2, width=10, height=1)
        a = build(self.row, "clock 12:00\nbody", ["text"], region)
        b = build(self.row, "clock 12:01\nbody", ["text"], region)
        self.assertEqual(a["snapshot_id"], b["snapshot_id"])
        cache = Observations()
        cache.finish(a)
        self.assertTrue(cache.finish(b, a["snapshot_id"])["unchanged"])
        self.assertFalse(cache.finish(b, "unknown")["since_known"])

    def test_known_credentials_are_masked_without_moving_cells(self):
        from unittest.mock import patch
        from cosmos_tui.features.agent.terminal import TerminalTools

        with patch(
            "cosmos_tui.features.agent.profile.load_profile",
            return_value=({}, {"fixture": "secret-key"}),
        ):
            self.assertEqual(
                TerminalTools.redact("secret-key [ OK ]"), "********** [ OK ]"
            )
