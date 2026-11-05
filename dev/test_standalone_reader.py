import tempfile
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

from cosmos_tui.features.reader.standalone import ReaderApp


class StandaloneReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_resize_search_and_quit_without_service(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'note.md'
            path.write_text('# Reader fixture\n\nA searchable standalone document.\n' * 20)
            with patch.dict(os.environ, {'XDG_CACHE_HOME': folder}), patch('cosmos_tui.core.rpc.call', new=AsyncMock(side_effect=AssertionError('Reader started coordinator'))):
                app = ReaderApp(path)
                async with app.run_test(size=(90, 30)) as pilot:
                    for _ in range(30):
                        await pilot.pause(0.05)
                        if app.reader_ui.loading.ready:
                            break
                    self.assertTrue(app.reader_ui.loading.ready, app.message)
                    self.assertFalse(app.reader_ui.loading.errors)
                    self.assertEqual(app.active().width, 90)
                    await pilot.press('r', 'right', 'escape')
                    await pilot.press('/')
                    await pilot.press('s', 't', 'a', 'n', 'd', 'enter')
                    await pilot.press('escape')
                    await pilot.resize_terminal(65, 20)
                    await pilot.pause(0.2)
                    self.assertEqual(app.active().width, 65)
                    await pilot.press('q')
                self.assertTrue(app.closing)

    async def test_missing_file_fails_before_ui(self):
        with self.assertRaises(FileNotFoundError):
            ReaderApp('/not-present/reader-fixture.pdf')


class GraphicsShutdownTests(unittest.TestCase):
    def test_final_graphics_cleanup_does_not_access_destroyed_screens(self):
        from cosmos_tui.render.output import OutputController
        from types import SimpleNamespace

        graphics = SimpleNamespace(pending="delete-image", take=Mock(return_value="delete-image"))
        driver = Mock()
        app = SimpleNamespace(graphics=graphics, is_headless=False, _running=False, _driver=driver)
        # Deliberately no screen: Textual has already emptied its screen stack.
        OutputController(app).flush_graphics()
        driver.write.assert_called_once_with("delete-image")
        driver.flush.assert_called_once()
