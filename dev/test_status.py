# ruff: noqa: E402
"""Status alignment/clicks and desktop-first Rime discovery."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe
from cosmos_tui.features.status.bar import StatusBar
from cosmos_tui.features.ime.config import configuration


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_layout_colored_button_and_independent_ime_clicks(self):
        app = Probe()
        async with app.run_test(size=(100, 30)) as pilot:
            bar = app.query_one("#status", StatusBar)
            bar.present(
                label="COSMOS",
                index=1,
                name="bash",
                path="~/Program",
                branch="main",
                clock="12:00 Oct 22",
            )
            text = bar._content
            self.assertEqual(text.cell_len, 100)
            self.assertIn("1 bash", text.plain)
            self.assertNotIn("¹", text.plain)
            self.assertIn("~/Program (main)", text.plain)
            self.assertTrue(text.plain.endswith("12:00 Oct 22 "))
            self.assertNotIn("|", text.plain)
            self.assertIn("En", text.plain)
            app.ime.toggle = AsyncMock()
            app.ime.toggle_width = AsyncMock()
            language = next(
                left for left, _, action in bar.hits if action == "language"
            )
            width = next(left for left, _, action in bar.hits if action == "width")
            await pilot.click("#status", offset=(language + 1, 0))
            await pilot.click("#status", offset=(width + 1, 0))
            app.ime.toggle.assert_awaited_once()
            app.ime.toggle_width.assert_awaited_once()
            app.settings["status_colors"] = {
                "image": "#208040",
                "foreground": "#ffffff",
            }
            bar.present(
                label="IMAGE",
                index=1,
                name="bash",
                path="",
                branch="",
                clock="12:00 Oct 22",
                mode="image",
            )
            self.assertEqual(bar.start_width, 7)
            self.assertIn(
                "#208040", str(bar._content.get_style_at_offset(app.console, 0))
            )

    async def test_focus_modes_and_reader_metadata(self):
        import base64
        import json
        from types import SimpleNamespace

        app = Probe()
        async with app.run_test(size=(120, 30)):
            bar = app.query_one("#status", StatusBar)
            for program, label in [
                ("bash", "COSMOS"),
                ("opencode", "AGENT"),
                ("yazi", "FILES"),
            ]:
                app.backend.request = AsyncMock(return_value=["\t" + program])
                app.status.cached = None
                await app.status.refresh()
                self.assertTrue(bar._content.plain.startswith(" " + label + " "))
            for path, label in [("/tmp/demo.png", "IMAGE"), ("/tmp/demo.pdf", "DOC")]:
                pane = app.active()
                pane.viewer = base64.b64encode(
                    json.dumps(dict(path=path, page=2)).encode()
                ).decode()
                app.reader_ui.frames[pane.id] = SimpleNamespace(
                    source_size=(800, 600), scale=0.5
                )
                app.reader_ui.pages[pane.id] = 4
                await app.status.refresh()
                self.assertTrue(bar._content.plain.startswith(" " + label + " "))
                self.assertNotIn("800×600px", bar._content.plain)
                self.assertNotIn("50%", bar._content.plain)

    async def test_path_depth_length_alignment_and_separators(self):
        from cosmos_tui.features.status.bar import short_path

        self.assertEqual(short_path("/one/two/three/four", 2, 40), "…/three/four")
        self.assertLessEqual(len(short_path("/very/long/path", 0, 8)), 8)
        app = Probe()
        async with app.run_test(size=(100, 30)):
            bar = app.query_one("#status", StatusBar)
            for align in ("left", "center", "right"):
                for separator, glyph in (
                    ("slash", "╱"),
                    ("vertical", "│"),
                    ("powerline", ""),
                    ("none", ""),
                ):
                    app.settings.update(
                        status_path_depth=2,
                        status_path_max_length=20,
                        status_path_align=align,
                        status_separator=separator,
                    )
                    bar.present(
                        label="COSMOS",
                        index=3,
                        name="bash",
                        path="/one/two/three/four",
                        branch="",
                        clock="12:00",
                    )
                    self.assertEqual(bar._content.cell_len, 100)
                    self.assertIn("…/three/four", bar._content.plain)
                    if glyph:
                        self.assertIn(glyph, bar._content.plain)
                    index = bar._content.plain.index("3 bash")
                    self.assertIn(
                        "#e8a662",
                        str(bar._content.get_style_at_offset(app.console, index)),
                    )
                    path_x = bar._content.plain.index("…/three/four")
                    if align == "left":
                        self.assertLess(path_x, 30)
                    if align == "center":
                        self.assertTrue(35 < path_x < 60)
                    if align == "right":
                        self.assertGreater(path_x, 60)

    async def test_direction_gradient_endpoint_and_capsule_colors(self):
        from cosmos_tui.features.status.bar import transition

        for kind, pair in (("powerline", ("", "")), ("capsule", ("", ""))):
            for direction, glyph in zip(("left", "right"), pair):
                seam = transition(kind, "#112233", "#445566", direction)
                self.assertEqual(seam.plain, glyph)
                style = seam.style
                self.assertEqual(
                    style.color.name, "#445566" if direction == "left" else "#112233"
                )
                self.assertEqual(
                    style.bgcolor.name, "#112233" if direction == "left" else "#445566"
                )
        app = Probe()
        async with app.run_test(size=(100, 30)):
            bar = app.query_one("#status", StatusBar)
            for align in ("left", "right", "center"):
                app.settings.update(
                    status_path_align=align, status_separator="powerline"
                )
                bar.present(
                    label="COSMOS",
                    index=1,
                    name="bash",
                    path="/tmp",
                    branch="",
                    clock="12:00",
                )
                seam = bar._content.get_style_at_offset(app.console, len(" COSMOS "))
                self.assertEqual(seam.color.name, "#103027")
                self.assertEqual(seam.bgcolor.name, "#292d38")
                path_x = bar._content.plain.index(" /tmp ")
                self.assertEqual(
                    bar._content.plain[path_x - 1], "" if align == "left" else ""
                )
            app.settings["status_separator"] = "capsule"
            bar.present(
                label="COSMOS",
                index=1,
                name="bash",
                path="/tmp",
                branch="",
                clock="12:00",
            )
            self.assertTrue(bar._content.plain.startswith(""))
            self.assertIn(" /tmp ", bar._content.plain)
            self.assertEqual(bar._content.cell_len, 100)

    def test_config_priority_and_selected_schema(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CONFIG_HOME=directory),
        ):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("COSMOS_RIME_DATA", None)
                os.environ.pop("COSMOS_RIME_SCHEMA", None)
                root = Path(directory)
                for folder in ("cosmos/rime", "fcitx5/rime", "ibus/rime"):
                    data = root / folder
                    (data / "build").mkdir(parents=True)
                    (data / "build/luna_pinyin.schema.yaml").touch()
                    (data / "user.yaml").write_text(
                        "var:\n  previously_selected_schema: luna_pinyin\n"
                    )
                    self.assertEqual(configuration(), (data, "luna_pinyin"))
