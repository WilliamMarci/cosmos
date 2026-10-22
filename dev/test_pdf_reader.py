# ruff: noqa: E402
"""Real Poppler PDF search, outline, page jump and byte-limited cache acceptance."""

import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe
from pdf_fixture import make_pdf
from cosmos_tui.features.reader.media import Media
from cosmos_tui.features.reader.layout import Reader
from cosmos_tui.features.reader.cache import ByteCache
from cosmos_tui.features.reader.jump import PageJump
from cosmos_tui.ui.styles import DARK


class PDFTests(unittest.TestCase):
    def test_real_search_phrase_outline_and_no_redecode_on_query(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.pdf"
            make_pdf(path)
            media = Media()
            state = dict(path=str(path), page=2, zoom=1, pan=[0, 0])
            source, pages, _ = media.load(state)
            self.assertEqual(pages, 5)
            results, has_text = media.search(path, "HELLO world")
            self.assertTrue(has_text)
            self.assertEqual([r["page"] for r in results], [2, 5])
            self.assertGreaterEqual(len(results[0]["boxes"]), 2)
            with patch(
                "cosmos_tui.features.reader.media.tool",
                side_effect=AssertionError("Unexpected decoder"),
            ):
                highlighted = media.load(dict(state, query="hello world"))[0]
                self.assertIsNot(highlighted, source)
                self.assertEqual(highlighted.size, source.size)
            outline = media.info(path)[1]
            self.assertEqual(
                [(i["title"], i["page"], i["depth"]) for i in outline],
                [
                    ("Introduction", 1, 0),
                    ("Search chapter", 2, 1),
                    ("Last chapter", 5, 0),
                ],
            )
            frame = Reader(media).render(
                source,
                dict(state, navigation="outline"),
                pages,
                80,
                24,
                (8, 16),
                DARK,
                False,
            )
            self.assertTrue(
                any(isinstance(h[-1], tuple) and h[-1][1] == 5 for h in frame.hits)
            )
            media.release()
            self.assertEqual(
                sum(
                    cache.bytes
                    for cache in (
                        media.cache,
                        media.views,
                        media.thumbnails,
                        media.documents,
                    )
                ),
                0,
            )

    def test_cleared_cache_cannot_be_repopulated_by_stale_thumbnail(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from PIL import Image
        import io

        started, finish = Event(), Event()
        payload = io.BytesIO()
        Image.new("RGB", (40, 40), "white").save(payload, format="PNG")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.pdf"
            make_pdf(path)
            media = Media()

            def decode(*args):
                started.set()
                self.assertTrue(finish.wait(3))
                return payload.getvalue()

            with (
                patch("cosmos_tui.features.reader.media.tool", side_effect=decode),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                pending = pool.submit(
                    media.thumbnail, dict(path=str(path), page=1), (30, 30)
                )
                self.assertTrue(started.wait(3))
                media.release()
                finish.set()
                self.assertIsNotNone(pending.result(timeout=3))
            self.assertEqual(media.thumbnails.bytes, 0)

    def test_byte_lru_recency_resize_and_oversize(self):
        cache = ByteCache(6, len)
        cache["a"] = "aaa"
        cache["b"] = "bbb"
        _ = cache["a"]
        cache["c"] = "ccc"
        self.assertNotIn("b", cache)
        self.assertLessEqual(cache.bytes, 6)
        cache.resize(3)
        self.assertEqual(len(cache), 1)
        cache["large"] = "x" * 20
        self.assertNotIn("large", cache)


class PDFUITests(unittest.IsolatedAsyncioTestCase):
    async def test_rapid_typing_then_enter_preserves_complete_search(self):
        from textual.events import Key
        from cosmos_tui.features.search.bar import BottomSearch
        from unittest.mock import AsyncMock

        app = Probe()
        provider = AsyncMock(return_value="1/2")
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(BottomSearch("PDF", provider, steps=True))
            await pilot.pause()
            for character in "hello world":
                await app.inputs.on_event(Key(character, character))
            await app.inputs.on_event(Key("enter", "\r"))
            await pilot.pause()
            provider.assert_awaited_once_with("hello world", 0)

    async def test_unchanged_active_page_reuses_frame_and_close_releases_cache(self):
        from textual.events import Key

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.pdf"
            make_pdf(path)
            app = Probe()
            app.settings["viewer_prefetch"] = False
            try:
                async with app.run_test(size=(80, 24)):
                    state = dict(path=str(path), page=2, zoom=1, pan=[0, 0], query="")
                    pane = app.active()
                    pane.viewer = base64.b64encode(json.dumps(state).encode()).decode()
                    with patch.object(
                        app.reader_ui.media, "load", wraps=app.reader_ui.media.load
                    ) as load:
                        first = await app.reader_ui.prepare(pane)
                        second = await app.reader_ui.prepare(pane)
                        self.assertIs(first, second)
                        self.assertEqual(load.call_count, 1)
                    await app.reader_ui.on_key(Key("q", "q"), pane)
                    self.assertFalse(app.reader_ui.frames)
                    self.assertEqual(app.reader_ui.media.cache.bytes, 0)
                    self.assertEqual(app.reader_ui.reader.cache.bytes, 0)
            finally:
                await app.reader_ui.close()

    async def test_search_moves_across_pages_and_jump_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.pdf"
            make_pdf(path)
            app = Probe()
            app.settings["viewer_prefetch"] = False
            try:
                async with app.run_test(size=(90, 30)) as pilot:
                    state = dict(path=str(path), page=1, zoom=1, pan=[0, 0], query="")
                    app.active().viewer = base64.b64encode(
                        json.dumps(state).encode()
                    ).decode()
                    app.reader_ui.pages["%0"] = 5
                    await pilot.press("slash", *"hello world", "enter")
                    self.assertEqual(
                        json.loads(base64.b64decode(app.active().viewer))["page"], 2
                    )
                    await pilot.press("f3")
                    self.assertEqual(
                        json.loads(base64.b64decode(app.active().viewer))["page"], 5
                    )
                    await pilot.press("escape", "g")
                    self.assertIsInstance(app.screen, PageJump)
                    app.screen.query_one("#jump-value").value = "99"
                    await pilot.press("enter")
                    self.assertIsInstance(app.screen, PageJump)
                    app.screen.query_one("#jump-value").value = "3"
                    await pilot.press("enter")
                    self.assertEqual(
                        json.loads(base64.b64decode(app.active().viewer))["page"], 3
                    )
            finally:
                await app.reader_ui.close()
