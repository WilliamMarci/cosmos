"""Rich books, persistent bounded cache, adaptive PDF pages and movable UI Mods."""

import base64
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe, snapshot
from cosmos_tui.features.reader.disk import DiskCache
from cosmos_tui.features.reader.documents import Documents, chapters
from cosmos_tui.features.reader.media import Media
from cosmos_tui.features.reader.raster import render_pdf
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.status.bar import StatusBar
from cosmos_tui.mods.api import ModAPI
from cosmos_tui.ui.styles import DARK
from PIL import Image
from textual.widgets import ListView

ROOT = Path(__file__).resolve().parents[1]


def png(size=(16, 16)):
    data = io.BytesIO()
    Image.new("RGB", size, "red").save(data, format="PNG")
    return data.getvalue()


def book(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/book.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>',
        )
        archive.writestr(
            "OPS/a.xhtml",
            '<h1>First chapter</h1><p>Hello <b>世界</b></p><img src="images/one.png"/>',
        )
        archive.writestr("OPS/b.xhtml", "<h1>Second chapter</h1><p>Needle second</p>")
        archive.writestr("OPS/images/one.png", png())


class DiskTests(unittest.TestCase):
    def test_persistence_byte_eviction_corruption_and_clear_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DiskCache(directory, 1)
            generation = first.generation()
            first.save_image(("one",), Image.new("RGB", (20, 20), "red"), generation)
            second = DiskCache(directory, 1)
            self.assertEqual(second.image(("one",)).size, (20, 20))
            second.path(("one",), ".png").write_bytes(b"broken")
            self.assertIsNone(second.image(("one",)))
            first.write(("a",), ".json", b"a" * 700000, generation)
            first.write(("b",), ".json", b"b" * 700000, generation)
            self.assertIsNone(first.read(("a",), ".json"))
            self.assertIsNotNone(first.read(("b",), ".json"))
            first.clear()
            first.save_json(("late",), {"late": True}, generation)
            self.assertIsNone(second.json(("late",)))
            self.assertLessEqual(
                sum(p.stat().st_size for p in Path(directory).glob("*.json")), 1024**2
            )

    def test_bitmap_reuse_across_media_instances_and_file_invalidation(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
        ):
            path = Path(directory) / "one.png"
            path.write_bytes(png())
            first = Media()
            first.load({"path": str(path)})
            second = Media()
            with patch.object(second.disk, "image", wraps=second.disk.image) as cached:
                result = second.load({"path": str(path)})
                self.assertEqual(result[0].size, (16, 16))
                self.assertTrue(
                    second.disk.path(
                        first.identity(path) + ("bitmap-v3", 1, 2400, 32), ".png"
                    ).is_file()
                )
                cached.assert_called_once()
            path.write_bytes(png((24, 24)))
            self.assertEqual(second.load({"path": str(path)})[0].size, (24, 24))


class RasterTests(unittest.TestCase):
    def test_decoder_budget_and_pixel_budget_reduce_resolution(self):
        calls = []

        def tool(*args):
            edge = int(args[args.index("-scale-to") + 1])
            calls.append(edge)
            if edge > 1200:
                raise ValueError("decoder output exceeds budget")
            return png((edge, edge))

        image, edge = render_pdf("large.pdf", 1, tool, 2400, 32)
        self.assertEqual(calls, [2400, 1200])
        self.assertEqual(image.size, (1200, 1200))
        self.assertEqual(edge, 1200)
        calls.clear()

        def noise(*args):
            edge = int(args[args.index("-scale-to") + 1])
            calls.append(edge)
            return png((edge, edge))

        image, edge = render_pdf("large.pdf", 1, noise, 2400, 4)
        self.assertLess(image.width * image.height * 3, 4 * 1024**2)
        self.assertGreater(len(calls), 1)

    @unittest.skipUnless(shutil.which("pdftoppm"), "requires Poppler")
    def test_real_pdf_with_page_image_larger_than_three_megabytes(self):
        from pypdf import PdfWriter
        from pypdf.generic import (
            DictionaryObject,
            NameObject,
            NumberObject,
            DecodedStreamObject,
        )

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
        ):
            path = Path(directory) / "large.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=600, height=660)
            bitmap = DecodedStreamObject()
            bitmap.set_data(os.urandom(1000 * 1100 * 3))
            bitmap.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(1000),
                    NameObject("/Height"): NumberObject(1100),
                    NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/XObject"): DictionaryObject(
                        {NameObject("/Im0"): writer._add_object(bitmap)}
                    )
                }
            )
            content = DecodedStreamObject()
            content.set_data(b"q 600 0 0 660 0 0 cm /Im0 Do Q")
            page[NameObject("/Contents")] = writer._add_object(content)
            with path.open("wb") as stream:
                writer.write(stream)
            self.assertGreater(path.stat().st_size, 3 * 1024**2)
            media = Media()
            image, pages, _ = media.load({"path": str(path)})
            self.assertEqual(pages, 1)
            self.assertLessEqual(max(image.size), 2400)
            second = Media()
            with patch(
                "cosmos_tui.features.reader.media.render_pdf",
                side_effect=AssertionError("decoded again"),
            ):
                self.assertEqual(second.load({"path": str(path)})[0].size, image.size)


class RichTests(unittest.TestCase):
    def test_markdown_html_and_epub_share_parser_and_book_spine(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
        ):
            root = Path(directory)
            md = root / "doc.md"
            md.write_text("# Title\n\nHello **world**\n\n|A|B|\n|-|-|\n|1|2|")
            page = root / "doc.html"
            page.write_text(
                "<h1>HTML</h1><p>Visible <em>text</em></p><script>NEVER_RENDER</script>"
            )
            epub = root / "book.epub"
            book(epub)
            docs = Documents(Media())
            pane = SimpleNamespace(width=80, height=14)
            for path, needle in (
                (md, "world"),
                (page, "Visible"),
                (epub, "First chapter"),
            ):
                frame, pages = docs.render(
                    pane, {"path": str(path), "page": 1}, DARK, (8, 16)
                )
                self.assertIn(needle, "\n".join(line.plain for line in frame.lines))
                self.assertGreaterEqual(pages, 1)
                self.assertNotIn(
                    "NEVER_RENDER", "\n".join(line.plain for line in frame.lines)
                )
            self.assertEqual(
                [name for name, _ in chapters(epub)], ["OPS/a.xhtml", "OPS/b.xhtml"]
            )
            self.assertTrue(docs.search(pane, {"path": str(epub)}, "Needle"))
            self.assertEqual(
                docs.asset(str(epub), "OPS/a.xhtml", "images/one.png").size, (16, 16)
            )
            with self.assertRaises(ValueError):
                docs.asset(str(epub), "OPS/a.xhtml", "../../outside.png")
            with self.assertRaises(ValueError):
                docs.asset(str(page), str(page), "https://example.com/image.png")
            # The second process-equivalent instance can reuse parsed documents.
            second = Documents(Media())
            with patch(
                "cosmos_tui.features.reader.documents.parse_html",
                side_effect=AssertionError("parsed again"),
            ):
                self.assertTrue(second.rows(str(md)))


class ModTests(unittest.IsolatedAsyncioTestCase):
    async def test_calendar_click_above_clock_move_disable_and_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "moved-package"
            shutil.copytree(ROOT / "mods/calendar", package)
            app = Probe()
            app.settings["ui_mod_paths"] = [str(package)]
            app.notification_events.publish = AsyncMock()
            async with app.run_test(size=(100, 30)) as pilot:
                app.ui_mods.refresh()
                self.assertEqual(
                    app.ui_mods.entries["calendar"]["entry_path"].parent, package
                )
                api = ModAPI(app.ui_mods, "calendar")
                with self.assertRaises(PermissionError):
                    await api.notify("denied")
                app.notification_events.publish.assert_not_awaited()
                bar = app.query_one(StatusBar)
                bar.present(
                    label="COSMOS",
                    index=0,
                    name="bash",
                    path="/tmp",
                    branch="",
                    clock="12:00 Oct 23",
                )
                x = next(x for x, _, action in bar.hits if action == "clock")
                await pilot.click("#status", offset=(x + 1, 0))
                await pilot.pause()
                screen = app.screen
                self.assertEqual(screen.mod_owner, "calendar")
                self.assertLessEqual(
                    screen.query_one("Frame").region.bottom, bar.region.y
                )
                self.assertEqual(screen.styles.background.a, 0)
                self.assertIn("12:00", app.export_screenshot())
                pane = app.active()
                cw, ch = app.reader_ui.cell_pixels()
                image = Image.new("RGB", (pane.width * cw, pane.height * ch), "white")
                tiles = screen.reader_images(pane.id, image, pane)
                self.assertIs(tiles, screen.reader_images(pane.id, image, pane))
                rect = screen.query_one("Frame").region
                for _, tile, x, y in tiles:
                    right, bottom = x + tile.width // cw, y + tile.height // ch
                    self.assertTrue(
                        right <= rect.x
                        or x >= rect.right
                        or bottom <= rect.y
                        or y >= rect.bottom
                    )
                previous = screen.month
                await pilot.press("right")
                self.assertEqual(screen.month, previous % 12 + 1)
                await pilot.press("question_mark")
                self.assertNotEqual(app.screen, screen)
                await pilot.press("escape")
                self.assertIs(app.screen, screen)
                app.settings["ui_mods"] = {
                    "calendar": {"enabled": True, "notifications": True}
                }
                app.ui_mods.refresh()
                await api.notify("allowed", level="info")
                app.notification_events.publish.assert_awaited_once_with(
                    "allowed", source="mod.calendar", ui_mod="calendar", level="info"
                )
                app.settings["ui_mods"]["calendar"]["enabled"] = False
                app.ui_mods.refresh()
                await pilot.pause()
                self.assertIs(app.screen, app._workspace_screen)
                self.assertFalse(app.ui_mods.activate_status("clock"))
                with self.assertRaises(PermissionError):
                    await api.notify("disabled")
            app.ui_mods.close()

    async def test_shared_settings_enable_and_notification_grant(self):
        state = snapshot()
        state["settings"].update(ui_mods={}, ui_mod_paths=[])

        async def rpc(method, params=None):
            if method == "state.snapshot":
                return state
            if method == "settings.get":
                return json.loads(json.dumps(state["settings"]))
            if method == "settings.replace":
                state["settings"] = json.loads(json.dumps(params))
                return {}
            return []

        app = Probe()
        with patch("cosmos_tui.core.rpc.call", side_effect=rpc):
            async with app.run_test(size=(100, 30)) as pilot:
                app.push_screen(Palette("ui_mod:calendar"))
                await pilot.pause()
                menu = app.screen
                menu.query_one(ListView).index = 1
                await pilot.press("right")
                self.assertTrue(
                    state["settings"]["ui_mods"]["calendar"]["notifications"]
                )
                menu.query_one(ListView).index = 0
                await pilot.press("right")
                self.assertFalse(state["settings"]["ui_mods"]["calendar"]["enabled"])
        app.ui_mods.close()


class RichUITests(unittest.IsolatedAsyncioTestCase):
    async def test_document_navigation_search_jump_and_close(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CACHE_HOME=directory),
        ):
            path = Path(directory) / "long.md"
            path.write_text(
                "# Heading\n\n"
                + "\n\n".join("Paragraph " + str(i) + " Needle" for i in range(80))
            )
            app = Probe()
            async with app.run_test(size=(80, 24)):
                pane = app.active()
                pane.viewer = base64.b64encode(
                    json.dumps({"path": str(path)}).encode()
                ).decode()
                frame = await app.reader_ui.prepare(pane)
                self.assertGreater(app.reader_ui.pages[pane.id], 1)
                self.assertIn("Heading", "\n".join(line.plain for line in frame.lines))
                result = await app.reader_ui.search_document(
                    pane.id, str(path), "Needle", 0
                )
                self.assertIn("1/", result)
                from textual.events import Key

                await app.reader_ui.on_key(Key("right_square_bracket", "]"), pane)
                self.assertEqual(json.loads(base64.b64decode(pane.viewer))["page"], 2)
                await app.reader_ui.on_key(Key("q", "q"), pane)
                self.assertFalse(pane.viewer)
            await app.reader_ui.close()
