"""Quick previews and file navigation regression boundaries."""

from concurrent.futures import Future
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zipfile
from PIL import Image
from rich.console import Console
from cosmos_tui.features.files.view import FileManager
from cosmos_tui.features.files.style import appearance
from cosmos_tui.features.reader.media import Media
from cosmos_tui.features.reader.documents import Documents
from cosmos_tui.features.reader.opener import preview
from cosmos_tui.features.reader.preview import QuickPreview, Preview
from cosmos_tui.input import keymap
from cosmos_tui.ui.styles import DARK


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_focus_hidden_binding_and_header(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("a", "b", "c"):
                (root / name).mkdir()
            (root / ".hidden").write_text("hidden")
            controller = SimpleNamespace(
                app=SimpleNamespace(
                    settings={}, graphics=SimpleNamespace(enabled=False)
                ),
                update_viewer=AsyncMock(),
            )
            manager = FileManager(controller)
            state = dict(kind="files", path=str(root / "b"), cursor=0)
            pane = SimpleNamespace(id="%0", width=100, height=22)
            await manager.key(SimpleNamespace(key="left", character=None), pane, state)
            self.assertEqual(state["path"], str(root))
            self.assertEqual(state["cursor"], 1)
            self.assertEqual(keymap.resolve("files", "h", {}).target, ".")
            await manager.key(
                SimpleNamespace(key="full_stop", character="."), pane, state
            )
            self.assertTrue(state["show_hidden"])
            self.assertIn(".hidden", [i["name"] for i in manager.listing(state)])
            ordinary = dict(name="visible", link=False, directory=False, mode=0)
            hidden = dict(ordinary, name=".hidden")
            self.assertNotEqual(
                appearance(ordinary, DARK)[0], appearance(hidden, DARK)[0]
            )
            frame = manager.render(pane, state, DARK, (8, 16))
            style = frame.lines[0].get_style_at_offset(Console(), 1)
            self.assertEqual(style.bgcolor.name, DARK["base"])


class PreviewTests(unittest.TestCase):
    def test_shared_image_pdf_epub_and_markdown(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict("os.environ", {"XDG_CACHE_HOME": temp}),
        ):
            root = Path(temp)
            media = Media()
            docs = Documents(media)
            image = Image.new("RGB", (200, 300), "red")
            os.mkfifo(root / "pipe.png")
            self.assertEqual(
                preview(root / "pipe.png", (80, 100), media=media, documents=docs)
                .lines[0]
                .plain,
                "Special file",
            )
            image.save(root / "image.png")
            image.save(root / "book.pdf", "PDF")
            pixels = io.BytesIO()
            image.save(pixels, format="PNG")
            for version in (2, 3):
                path = root / f"book{version}.epub"
                with zipfile.ZipFile(path, "w") as book:
                    book.writestr(
                        "META-INF/container.xml",
                        '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
                    )
                    meta = (
                        '<metadata><meta name="cover" content="cover"/></metadata>'
                        if version == 2
                        else ""
                    )
                    prop = ' properties="cover-image"' if version == 3 else ""
                    book.writestr(
                        "OPS/book.opf",
                        f'<package xmlns="http://www.idpf.org/2007/opf">{meta}<manifest><item id="cover" href="cover.png" media-type="image/png"{prop}/></manifest></package>',
                    )
                    book.writestr("OPS/cover.png", pixels.getvalue())
                result = preview(path, (80, 100), media=media, documents=docs)
                self.assertIsNotNone(result.image)
                self.assertEqual(result.image.getpixel((0, 0)), (255, 0, 0))
            for name in ("image.png", "book.pdf"):
                result = preview(root / name, (80, 100), media=media, documents=docs)
                self.assertLessEqual(result.image.width, 80)
                self.assertLessEqual(result.image.height, 100)
            # Both tiny images and PDF rasterization must fill the available box.
            for name in ("image.png", "book.pdf"):
                fitted = preview(
                    root / name, (600, 800), media=media, documents=docs
                ).image
                self.assertEqual(fitted.height, 800)
                self.assertLessEqual(fitted.width, 600)
            (root / "read.md").write_text("# Heading\n\nHello **Cosmos**.")
            result = preview(
                root / "read.md",
                (80, 100),
                media=media,
                documents=docs,
                columns=20,
                rows=8,
            )
            self.assertIn("Cosmos", " ".join(line.plain for line in result.lines))
            self.assertNotIn("**", " ".join(line.plain for line in result.lines))

    def test_file_preview_composes_into_right_column_only(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict("os.environ", {"XDG_CACHE_HOME": temp}),
        ):
            root = Path(temp) / "files"
            root.mkdir()
            Image.new("RGB", (40, 60), "red").save(root / "image.png")
            media = Media()
            service = QuickPreview(media, Documents(media))
            app = SimpleNamespace(settings={}, graphics=SimpleNamespace(enabled=False))
            controller = SimpleNamespace(app=app)
            controller.quick_preview = (
                lambda owner, path, bounds, columns, rows: service.request(
                    owner, path, bounds, columns, rows, {}
                )
            )
            manager = FileManager(controller)
            pane = SimpleNamespace(id="%0", width=100, height=22)
            state = dict(kind="files", path=str(root), cursor=0)
            try:
                waiting = manager.render(pane, state, DARK, (8, 16))
                self.assertIn(
                    "image.png", "\n".join(line.plain for line in waiting.lines)
                )
                for future in list(service.pending.values()):
                    future.result(timeout=5)
                import time

                for _ in range(100):
                    if service.revision:
                        break
                    time.sleep(0.01)
                frame = manager.render(pane, state, DARK, (8, 16))
                self.assertGreater(
                    sum(1 for pixel in frame.image.getdata() if pixel == (255, 0, 0)), 0
                )
                self.assertFalse(
                    any(
                        pixel == (255, 0, 0)
                        for pixel in frame.image.crop((0, 0, 60 * 8, 22 * 16)).getdata()
                    )
                )
                self.assertTrue(
                    any("▀" in line.plain or "▄" in line.plain for line in frame.lines)
                )
            finally:
                service.close()

    def test_nonblocking_request_error_cache_and_stale_result(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict("os.environ", {"XDG_CACHE_HOME": temp}),
        ):
            root = Path(temp)
            (root / "a.png").write_bytes(b"not an image")
            (root / "b.png").write_bytes(b"other")
            media = Media()
            service = QuickPreview(media, Documents(media))
            try:
                future = Future()
                with patch.object(service.pool, "submit", return_value=future):
                    result = service.request("%0", root / "a.png", (40, 60), 5, 4, {})
                    self.assertTrue(result.loading)
                    key = service.latest["%0"]
                    service.latest["%0"] = ("new selection",)
                    future.set_result(Preview(error="old failure"))
                    self.assertNotIn(key, service.cache)
                service.cache.clear()
                f = Future()
                with patch.object(service.pool, "submit", return_value=f):
                    self.assertTrue(
                        service.request(
                            "%0", root / "b.png", (40, 60), 5, 4, {}
                        ).loading
                    )
                    f.set_exception(ValueError("Cannot decode image"))
                    result = service.request("%0", root / "b.png", (40, 60), 5, 4, {})
                    self.assertEqual(result.error, "Cannot decode image")
            finally:
                service.close()
