"""Behavioral checks for multicolumn/scroll rich documents and asset controls."""

import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe, snapshot
from cosmos_tui.features.reader.documents import Documents
from cosmos_tui.features.reader.media import Media
from cosmos_tui.features.reader.flow import geometry, ICON_EDGE
from cosmos_tui.features.reader.rich_input import key, action
from cosmos_tui.ui.styles import DARK
from cosmos_tui.terminal.tmux import Pane
from PIL import Image
from textual.events import Key


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_columns_scroll_paragraphs_outline_and_inspector(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
        ):
            path = Path(directory) / "book.md"
            path.write_text(
                "# First\n\n"
                + "\n\n".join("Paragraph %s words" % i for i in range(50))
                + "\n\n# Second\n\nFinal text"
            )
            app = Probe()
            async with app.run_test(size=(160, 28)) as pilot:
                self.assertIs(
                    app.reader_ui.documents.image_reader, app.reader_ui.reader
                )
                pane = app.active()
                pane.width, pane.height = 160, 27
                state = dict(path=str(path), columns=2, reading_mode="scroll", row=0)
                await app.reader_ui.update_viewer(pane, state)
                frame = await app.reader_ui.prepare(pane)
                self.assertEqual(geometry(pane, state)[3], 2)
                self.assertGreater(app.reader_ui.pages[pane.id], 1)
                self.assertTrue(
                    any("Paragraph" in line.plain[90:] for line in frame.lines[:-1])
                )
                await key(app.reader_ui, Key("down", None), pane, state)
                self.assertEqual(state["row"], 1)
                await key(app.reader_ui, Key("right", None), pane, state)
                self.assertEqual(state["row"], 53)
                await key(app.reader_ui, Key("tab", None), pane, state)
                first = state["selected_block"]
                await key(app.reader_ui, Key("tab", None), pane, state)
                self.assertNotEqual(first, state["selected_block"])
                await key(app.reader_ui, Key("shift+tab", None), pane, state)
                self.assertEqual(first, state["selected_block"])
                await action(app.reader_ui, pane, state, "sidebar")
                self.assertFalse(state["thumbnails"])
                await action(app.reader_ui, pane, state, "columns")
                self.assertEqual(state["columns"], 3)
                await action(app.reader_ui, pane, state, "mode")
                self.assertEqual(state["reading_mode"], "pages")
                info = app.reader_ui.documents.info(pane, state)[1]
                await action(app.reader_ui, pane, state, "outline", info[-1]["line"])
                frame, _ = app.reader_ui.documents.render(
                    pane, dict(state, thumbnails=True), DARK, (10, 20)
                )
                self.assertTrue(
                    any("Second" in line.plain[:26] for line in frame.lines)
                )
                self.assertTrue(json.loads(base64.b64decode(pane.viewer)))
                await pilot.press("v", "tab", "down")
                active = json.loads(base64.b64decode(pane.viewer))
                self.assertEqual(active["reading_mode"], "scroll")
                self.assertIn("selected_block", active)

            await app.reader_ui.close()

    async def test_settings_actions_defaults_and_punctuation_page_turns(self):
        from copy import deepcopy
        from cosmos_tui.features.settings.panel import Palette
        from cosmos_tui.features.navigation.menus import ActionDrawer
        from cosmos_tui.core import rpc
        from textual.widgets import ListView

        settings = dict(
            viewer_rich_columns="auto",
            viewer_rich_mode="pages",
            viewer_inline_image_rows=8,
            viewer_icon_max_px=64,
        )

        async def call(method, params=None):
            if method == "state.snapshot":
                return dict(snapshot(), settings=deepcopy(settings))
            if method == "settings.get":
                return deepcopy(settings)
            if method == "settings.replace":
                settings.clear()
                settings.update(deepcopy(params))
                return deepcopy(settings)
            return {}

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
            patch.object(rpc, "call", side_effect=call),
        ):
            path = Path(directory) / "reader.md"
            path.write_text(
                "# Reader\n\n" + "\n\n".join("Paragraph %s" % i for i in range(140))
            )
            app = Probe()
            async with app.run_test(size=(90, 30)) as pilot:
                app.push_screen(Palette("reader_settings"))
                await pilot.pause()
                menu = app.screen
                row = next(
                    r for r in menu.rows if r.get("key") == "viewer_rich_columns"
                )
                await menu.cycle_choice(row, 1)
                self.assertEqual(settings["viewer_rich_columns"], "1")
                await pilot.press("escape")
                pane = app.active()
                pane.viewer = base64.b64encode(
                    json.dumps(dict(path=str(path))).encode()
                ).decode()
                state = app.reader_ui.state(pane)
                self.assertEqual(state["columns"], 1)
                state["columns"] = 2
                await app.reader_ui.update_viewer(pane, state)
                settings["viewer_rich_columns"] = "3"
                app.settings = deepcopy(settings)
                self.assertEqual(app.reader_ui.state(pane)["columns"], 2)
                frame = await app.reader_ui.prepare(pane)
                self.assertNotIn("[columns", frame.lines[-1].plain)
                from PIL import ImageColor

                button_hits = [h for h in frame.hits if h[-1][0] == "mode"]
                bx, by = button_hits[-1][:2]
                cw, ch = app.reader_ui.cell_pixels()
                self.assertEqual(
                    frame.image.getpixel((bx * cw, by * ch)),
                    ImageColor.getrgb(app.role_colors["mute"]),
                )
                self.assertTrue(any(h[-1] == ("columns", 0) for h in frame.hits))
                await pilot.press("full_stop")
                after = app.reader_ui.state(pane)
                self.assertEqual(after["page"], 2)
                await pilot.press("comma")
                self.assertEqual(app.reader_ui.state(pane)["page"], 1)
                await pilot.press("v", "full_stop")
                scroll = app.reader_ui.state(pane)
                self.assertEqual(scroll["reading_mode"], "scroll")
                self.assertEqual(scroll["row"], (pane.height - 1) * 2)
                await pilot.press("comma")
                self.assertEqual(app.reader_ui.state(pane)["row"], 0)
                app.action_context_actions()
                await pilot.pause()
                self.assertIsInstance(app.screen, ActionDrawer)
                ids = {r.get("id") for r in app.screen.entries}
                self.assertTrue(
                    {
                        "viewer.columns",
                        "viewer.reading_mode",
                        "viewer.search",
                        "viewer.outline",
                    }
                    <= ids
                )
                self.assertNotIn("viewer.zoom_in", ids)
                index = next(
                    i
                    for i, r in enumerate(app.screen.rows)
                    if r.get("id") == "viewer.columns"
                )
                app.screen.query_one(ListView).index = index
                app.screen.choose()
                await pilot.pause()
                self.assertEqual(app.reader_ui.state(pane)["columns"], 3)
            await app.reader_ui.close()

    def test_disk_restored_documents_render_plain_and_styled_text(self):
        from test_next_readers_mods import book
        from cosmos_tui.features.reader.documents import decoded

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
        ):
            root = Path(directory)
            markdown = root / "cached.md"
            markdown.write_text(
                "# Title\n\nPlain paragraph with **bold** and *italic* text.\n\nAnother paragraph."
            )
            epub = root / "cached.epub"
            book(epub)
            pane = Pane("%0", 0, 0, 90, 30, True, [], "", (0, 0))
            for path in (markdown, epub):
                state = dict(path=str(path), columns=1)
                first, first_pages = Documents(Media()).render(
                    pane, state, DARK, (10, 20)
                )
                # Fresh parser/layout caches must still render from persisted blocks.
                with patch(
                    "cosmos_tui.features.reader.documents.parse_html",
                    side_effect=AssertionError("Expected disk cache hit"),
                ):
                    reopened, reopened_pages = Documents(Media()).render(
                        pane, state, DARK, (10, 20)
                    )
                self.assertEqual(first_pages, reopened_pages)
                self.assertEqual(
                    [t.plain for t in first.lines], [t.plain for t in reopened.lines]
                )
                self.assertEqual(first.image.tobytes(), reopened.image.tobytes())
            for value in (None, ""):
                text = decoded(dict(text="Unstyled", style=value))
                self.assertEqual(text.style, "")

    def test_icons_natural_size_images_fold_and_wide_tables(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
        ):
            root = Path(directory)
            Image.new("RGB", (16, 16), "red").save(root / "icon.png")
            Image.new("RGB", (1200, 800), "blue").save(root / "large.png")
            path = root / "book.html"
            path.write_text(
                '<h1>Title</h1><img src="icon.png"><img src="large.png"><table><tr><td>'
                + "wide " * 60
                + "</td><td>"
                + "wide " * 40
                + "</td><td>"
                + "wide " * 40
                + "</td><td>世界</td></tr></table>"
            )
            doc = Documents(Media())
            pane = Pane("%0", 0, 0, 90, 40, True, [], "", (0, 0))
            state = dict(path=str(path), thumbnails=False, columns=1)
            rows = doc.layout(path, 86, state)
            image_blocks = [r.block for r in doc.rows(path) if r.image]
            icon, large = image_blocks
            self.assertEqual(ICON_EDGE, 64)
            self.assertFalse(any(r.table for r in rows if r.block == icon))
            self.assertTrue(any(r.table for r in rows if r.block == large))
            frame, _ = doc.render(pane, state, DARK, (10, 20))
            self.assertFalse(any(h[-1] == ("expand", icon) for h in frame.hits))
            self.assertTrue(any(h[-1] == ("expand", large) for h in frame.hits))
            red = sum(
                1
                for r, g, b in frame.image.get_flattened_data()
                if r > 200 and g < 30 and b < 30
            )
            self.assertEqual(red, 16 * 16)
            folded = doc.layout(path, 86, dict(state, collapsed_images=[large]))
            self.assertLess(len(folded), len(rows))
            table = next(r for r in doc.rows(path) if r.table)
            self.assertTrue(any(r.table and r.block == table.block for r in rows))
            frame, _ = doc.render(
                pane,
                dict(state, inspector=table.block, inspect_pan=[8, 0]),
                DARK,
                (10, 20),
            )
            self.assertTrue(any("wide" in line.plain for line in frame.lines))
            self.assertTrue(any(h[-1][0] == "back" for h in frame.hits))
            frame, _ = doc.render(
                pane,
                dict(state, inspector=large, inspect_zoom=2, inspect_pan=[2, 2]),
                DARK,
                (10, 20),
            )
            self.assertEqual(frame.image.size, (900, 800))


if __name__ == "__main__":
    unittest.main()
