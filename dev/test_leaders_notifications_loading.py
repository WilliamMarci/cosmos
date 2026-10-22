"""Multiple prefix routing, asynchronous loading cover and compact notice stack."""

import asyncio
import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import Probe
from textual.events import Key
from PIL import Image
from rich.text import Text
from cosmos_tui.features.reader.layout import ReadingFrame
from cosmos_tui.features.notifications.toast import NoticeToast, COLORS
from cosmos_tui.input import keymap
from cosmos_tui.ui.keyboard import key_phases


class OcclusionTests(unittest.TestCase):
    def test_notices_mask_only_their_own_pixel_rectangles(self):
        from cosmos_tui.render.graphics import Graphics
        from cosmos_tui.ui.cells import Rect

        source = Image.new("RGB", (200, 200), "white")
        graphics = Graphics()
        cover = graphics.cover(
            "pane", source, 0, 0, (10, 10), [Rect(10, 10, 5, 1)], "#1e212c"
        )
        self.assertEqual(cover.getpixel((105, 105)), (30, 33, 44))
        self.assertEqual(cover.getpixel((5, 105)), (255, 255, 255))
        self.assertIs(
            cover,
            graphics.cover(
                "pane", source, 0, 0, (10, 10), [Rect(10, 10, 5, 1)], "#1e212c"
            ),
        )


class PrefixTests(unittest.IsolatedAsyncioTestCase):
    async def test_secondary_prefixes_and_enter_are_distinct(self):
        app = Probe()
        app.settings["keybindings"] = {
            "workspace.split_vertical": ["leader2+v", "leader3+x"]
        }
        app.action_leader_key = AsyncMock()
        app.backend.send = AsyncMock()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("ctrl+a", "v")
            app.action_leader_key.assert_awaited_with("quotation_mark")
            app.prefix = False
            await app.inputs.on_event(Key("ctrl+m", None))
            await app.inputs.on_event(Key("x", "x"))
            self.assertEqual(app.action_leader_key.await_count, 2)
            app.prefix = False
            await pilot.press("enter")
            app.backend.send.assert_awaited_with("enter", None)
            self.assertFalse(app.prefix)
        self.assertEqual(keymap.display_binding("leader2+x", {}), "Ctrl+A → x")
        first, second = key_phases(["leader3+x"], settings={"leader3": "C-m"})
        self.assertIn("M", first)
        self.assertIn("X", second)
        with self.assertRaises(ValueError):
            keymap.validate({"workspace.palette": ["leader2+m"]}, {"leader2": "C-b"})

    async def test_unused_presets_leave_shell_chords_alone(self):
        app = Probe()
        app.backend.send = AsyncMock()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("ctrl+a")
            app.backend.send.assert_awaited_with("ctrl+a", None)
            self.assertFalse(app.prefix)

    async def test_editor_selects_leader3_preset(self):
        from cosmos_tui.features.settings.keybindings import KeyBindingEditor
        from textual.widgets import Input

        app = Probe()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                KeyBindingEditor(
                    next(c for c in keymap.COMMANDS if c.id == "workspace.palette")
                )
            )
            await pilot.pause()
            await pilot.click("#key-leader3")
            app.screen.query_one("#key-next", Input).value = "x"
            await pilot.pause()
            self.assertEqual(app.screen.values(), ["leader3+x"])


class LoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_probe_reloads_a_modified_image(self):
        import tempfile

        app = Probe()
        app.settings["viewer_prefetch"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            Image.new("RGB", (64, 64), "red").save(path)
            async with app.run_test(size=(80, 24)):
                pane = app.active()
                pane.viewer = base64.b64encode(
                    json.dumps(
                        dict(path=str(path), page=1, zoom=1, pan=[0, 0])
                    ).encode()
                ).decode()
                loading = app.reader_ui.loading
                loading.frame(pane)
                await loading.pending[pane.id]
                self.assertEqual(loading.frame(pane).source_size, (64, 64))
                Image.new("RGB", (72, 72), "blue").save(path)
                loading.probed[pane.id] = 0
                loading.frame(pane)
                await loading.pending[pane.id]
                self.assertEqual(loading.frame(pane).source_size, (72, 72))
            await app.reader_ui.close()

    async def test_oversize_image_keeps_navigation_and_retries_new_limit(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("a.png", "b.png", "c.png")]
            for path in paths:
                Image.new("RGB", (32, 32), "red").save(path)
            with paths[1].open("ab") as stream:
                stream.truncate(40 * 1024**2)
            app = Probe()
            app.action_error = AsyncMock()
            app.settings["viewer_prefetch"] = False
            app.settings["viewer_image_max_mb"] = 32
            async with app.run_test(size=(80, 24)):
                pane = app.active()
                pane.viewer = base64.b64encode(
                    json.dumps({"path": str(paths[1])}).encode()
                ).decode()
                loading = app.reader_ui.loading
                loading.frame(pane)
                await loading.pending[pane.id]
                self.assertIn("40.0 MiB", loading.errors[pane.id][1])
                self.assertIn("32 MiB", loading.errors[pane.id][1])
                self.assertEqual(app.reader_ui.frames[pane.id].selected, 1)
                await app.reader_ui.on_key(Key("right_square_bracket", "]"), pane)
                self.assertEqual(
                    json.loads(base64.b64decode(pane.viewer))["path"], str(paths[2])
                )
                loading.frame(pane)
                await loading.pending[pane.id]
                self.assertNotIn(pane.id, loading.errors)
                pane.viewer = base64.b64encode(
                    json.dumps({"path": str(paths[1])}).encode()
                ).decode()
                app.settings["viewer_image_max_mb"] = 64
                loading.frame(pane)
                await loading.pending[pane.id]
                self.assertNotIn(pane.id, loading.errors)
                self.assertEqual(loading.ready[pane.id][2].source_size, (32, 32))
                app.reader_ui.media.image_max_mb = 32
                with self.assertRaisesRegex(ValueError, "40.0 MiB"):
                    app.reader_ui.media.thumbnail({"path": str(paths[1])}, (20, 20))
            await app.reader_ui.close()

    async def test_pending_and_failed_viewers_never_return_shell_content(self):
        app = Probe()
        app.action_error = AsyncMock()
        async with app.run_test(size=(80, 24)):
            pane = app.active()
            pane.viewer = base64.b64encode(
                json.dumps({"path": "/tmp/book.pdf"}).encode()
            ).decode()
            ready = asyncio.Event()
            cw, ch = app.reader_ui.cell_pixels()
            image = Image.new("RGB", (pane.width * cw, pane.height * ch), "white")
            expected = ReadingFrame(
                image,
                [Text("PDF CONTENT")],
                range(1),
                0,
                [],
                24,
                0,
                80,
                1,
                (80, 24),
                (0, 0),
            )

            async def prepare(pane):
                await ready.wait()
                return expected

            app.reader_ui.prepare = prepare
            first = app.reader_ui.loading.frame(pane)
            self.assertTrue(any("Loading" in line.plain for line in first.lines))
            self.assertGreater(first.main_x, 0)
            self.assertNotEqual(
                first.image.getpixel((0, 0)),
                first.image.getpixel((first.main_x * 8 + 100, 100)),
            )
            self.assertTrue(all(line.cell_len <= pane.width for line in first.lines))
            self.assertIs(first.image, app.reader_ui.loading.frame(pane).image)
            task = app.reader_ui.loading.pending[pane.id]
            ready.set()
            await task
            self.assertIs(app.reader_ui.loading.frame(pane), expected)
            # A state-only transition retains the frame while cached content is composed.
            pane.viewer = base64.b64encode(
                json.dumps({"path": "/tmp/book.pdf", "page": 2}).encode()
            ).decode()
            self.assertIs(app.reader_ui.loading.frame(pane), expected)
            app.reader_ui.loading.missing[pane.id] = app.reader_ui.loading.key(pane)
            missing = app.reader_ui.loading.frame(pane)
            self.assertIsNot(missing, expected)
            # Sidebar/footer pixels survive a genuinely missing page.
            self.assertEqual(
                missing.image.getpixel((0, 0)), expected.image.getpixel((0, 0))
            )
            self.assertEqual(
                missing.image.getpixel((0, missing.image.height - 1)),
                expected.image.getpixel((0, expected.image.height - 1)),
            )
            app.reader_ui.clear_cache()
            app.reader_ui.prepare = AsyncMock(side_effect=RuntimeError("bad PDF"))
            app.reader_ui.loading.frame(pane)
            await app.reader_ui.loading.pending[pane.id]
            failed = app.reader_ui.loading.frame(pane)
            self.assertTrue(any("Cannot load" in line.plain for line in failed.lines))
            app.action_error.assert_awaited_once()
        await app.reader_ui.close()


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeat_suffix_is_amber_and_fits_long_notice(self):
        app = Probe()
        async with app.run_test(size=(80, 24)):
            toast = NoticeToast()
            await app.mount(toast)
            for text in ("Failed", "Very long message " * 20):
                toast.present_notices(
                    [dict(id=1, text=text, count=12)],
                    80,
                    24,
                    app.role_colors,
                    pane_width=40,
                )
                suffix = next(r for r in toast.frame.runs if r.text == " ×12")
                self.assertEqual(suffix.foreground, COLORS["warning"])
                self.assertLessEqual(suffix.rect.x + suffix.rect.width, 77)
                self.assertLessEqual(toast.frame.bounds.height, 2)

    async def test_stack_order_color_two_line_limit_and_action_identity(self):
        app = Probe()
        notices = [
            dict(id=1, text="Short", level="success", session_id="$1"),
            dict(
                id=2,
                text="Long notice " * 30,
                level="error",
                actions=[dict(id="ok", label="OK")],
            ),
        ]
        async with app.run_test(size=(80, 24)):
            toast = app.query_one(NoticeToast)
            toast.present_notices(notices, 80, 24, app.role_colors)
            markers = [run for run in toast.frame.runs if run.text == "▐"]
            self.assertEqual(len(markers), 3)
            self.assertEqual(markers[-1].foreground, COLORS["success"])
            self.assertEqual(markers[0].foreground, COLORS["error"])
            old = next(h for h in toast.frame.hits if h.action == "1:__dismiss__")
            new = next(h for h in toast.frame.hits if h.action == "2:ok")
            self.assertGreater(old.rect.y, new.rect.y)
            self.assertEqual(toast.frame.bounds.y, 0)
            original_post_message = toast.post_message
            toast.post_message = Mock()
            toast.choose("1:__dismiss__")
            event = toast.post_message.call_args.args[0]
            self.assertEqual((event.notification, event.action), (1, "__dismiss__"))
            toast.post_message = original_post_message
            self.assertTrue(any(run.text.startswith("¹ ") for run in toast.frame.runs))
            toast.present_notices(notices, 80, 24, app.role_colors, pane_width=40)
            self.assertTrue(
                all(run.rect.width == 28 for run in toast.frame.runs if not run.text)
            )
            for width in (2, 4, 10, 60):
                toast.present_notices(notices, width, 8, app.role_colors)
            toast.present_notices([], 80, 24, app.role_colors)
            self.assertFalse(toast.display)
