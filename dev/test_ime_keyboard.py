# ruff: noqa: E402
"""Real Rime integration, per-target composition and responsive key previews."""

import ctypes.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, PropertyMock, patch
from types import SimpleNamespace

from textual.dom import NoScreen

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from test_navigation import Probe, snapshot
from cosmos_tui.features.settings.panel import Palette
from cosmos_tui.features.settings.keybindings import KeyBindingEditor
from cosmos_tui.input import keymap
from cosmos_tui.terminal.tmux import Pane
from cosmos_tui.ui.help import Help
from cosmos_tui.ui.keyboard import KeyboardPreview, physical_keys

DATA = Path.home() / ".config/ibus/rime"
REAL_RIME = (
    ctypes.util.find_library("rime") and (DATA / "build/rime_ice.schema.yaml").exists()
)


class KeyboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_detached_candidate_surface_is_replaced(self):
        from cosmos_tui.features.ime.controller import IMEController
        from cosmos_tui.ui.cells import Rect

        screen = SimpleNamespace(mount=AsyncMock())
        app = SimpleNamespace(screen=screen, ui_registry=Mock(), role_colors={}, settings={})
        ime = IMEController(app)
        ime.enabled = True
        ime.engine = Mock()
        ime.engine.context.return_value = {"preedit": "ni"}
        old = Mock()
        old.is_mounted = True
        old.remove = AsyncMock()
        type(old).screen = PropertyMock(side_effect=NoScreen("node has no screen"))
        ime.surface = old
        pane = SimpleNamespace(x=0, y=0, width=80, height=24)
        replacement = Mock()
        with (
            patch.object(ime, "target", return_value=(("pane", "%0"), (0, 0), pane)),
            patch("cosmos_tui.features.ime.controller.CellSurface", return_value=replacement),
            patch("cosmos_tui.features.ime.controller.compose", return_value=Rect(0, 0, 1, 1)),
        ):
            await ime.refresh()
        old.remove.assert_awaited_once()
        screen.mount.assert_awaited_once_with(replacement)
        self.assertIs(ime.surface, replacement)
        replacement.present.assert_called_once()

    async def test_responsive_help_and_live_key_editor(self):
        app = Probe()
        async with app.run_test(size=(100, 50)) as pilot:
            app.push_screen(Help("Keys", [("Leader m", "Menu")]))
            await pilot.pause()
            self.assertTrue(app.screen.query_one(KeyboardPreview).display)
            await pilot.resize_terminal(65, 24)
            self.assertFalse(app.screen.query_one(KeyboardPreview).display)
            await pilot.press("escape")
            await pilot.resize_terminal(100, 40)
            app.push_screen(
                KeyBindingEditor(
                    next(c for c in keymap.COMMANDS if c.id == "global.start")
                )
            )
            await pilot.pause()
            keyboard = app.screen.query_one(KeyboardPreview)
            self.assertTrue(keyboard.display)
            self.assertIn("M", physical_keys(keyboard.keys))
            app.screen.query_one("#key-value").value = "ctrl+x"
            await pilot.pause()
            self.assertIn("X", physical_keys(keyboard.keys))
        self.assertEqual(
            physical_keys(["leader+quotation_mark"]), {"Ctrl", "B", "Shift", "'"}
        )


@unittest.skipUnless(REAL_RIME, "requires librime and compiled rime_ice data")
class IMETests(unittest.IsolatedAsyncioTestCase):
    async def test_real_rime_repeated_candidate_paging(self):
        from cosmos_tui.features.ime.rime import Rime

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ, XDG_STATE_HOME=directory, COSMOS_RIME_DATA=str(DATA)
            ),
        ):
            engine = Rime()
            target = ("pane", "%paging-test")
            try:
                for char in "shi":
                    engine.process(target, ord(char))
                self.assertEqual(engine.context(target)["page"], 0)
                for expected in range(1, 6):
                    engine.process(target, 0xFF56)
                    self.assertEqual(engine.context(target)["page"], expected)
                for expected in range(4, -1, -1):
                    engine.process(target, 0xFF55)
                    self.assertEqual(engine.context(target)["page"], expected)
            finally:
                engine.close()

    async def test_real_rime_in_command_assistant_custom_editor(self):
        from test_assistant import LayerProbe
        from cosmos_tui.ui.editor import CellEditor

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ, XDG_STATE_HOME=directory, COSMOS_RIME_DATA=str(DATA)
            ),
        ):
            app = LayerProbe()
            app.backend.paste = AsyncMock()
            try:
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    editor = app.screen.query_one(CellEditor)
                    editor.assign("", 0)
                    app.screen.capture()
                    await pilot.press("ctrl+b", "i", *"nihao")
                    target = app.ime.target()[0]
                    self.assertEqual(target, ("input", editor))
                    self.assertIn("你好", app.ime.engine.context(target)["candidates"])
                    self.assertTrue(app.ime.surface.display)
                    self.assertIs(app.ime.surface.screen, app.screen)
                    await pilot.press("space")
                    await pilot.pause()
                    self.assertEqual(editor.value, "你好")
                    self.assertEqual(app.screen.controller.input.text, "你好")
                    app.backend.paste.assert_not_awaited()
                    self.assertFalse(app.ime.engine.context(target)["preedit"])
                    await app.ime.toggle()
                    await app.ime.toggle_width()
                    await pilot.press("a")
                    self.assertEqual(editor.value, "你好ａ")
            finally:
                app.ime.close()

    async def test_real_candidates_targets_commit_and_width(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ, XDG_STATE_HOME=directory, COSMOS_RIME_DATA=str(DATA)
            ),
            patch("cosmos_tui.core.rpc.call", AsyncMock(return_value=snapshot())),
        ):
            app = Probe()
            app.backend.paste = AsyncMock()
            try:
                async with app.run_test(size=(100, 35)) as pilot:
                    await pilot.press("ctrl+b", "i")
                    self.assertTrue(app.ime.enabled)
                    await pilot.press(*"ni")
                    first = ("pane", "%0")
                    draft = app.ime.engine.context(first)["preedit"]
                    self.assertTrue(draft)
                    app.active().active = False
                    app.panes.append(Pane("%1", 0, 0, 100, 34, True, [], "", (0, 0)))
                    await pilot.press(*"hao")
                    self.assertEqual(app.ime.engine.context(first)["preedit"], draft)
                    app.active().active = False
                    app.panes[0].active = True
                    await pilot.press(*"hao")
                    self.assertIn("你好", app.ime.engine.context(first)["candidates"])
                    await pilot.press("space")
                    app.backend.paste.assert_awaited_once_with("你好", target="%0")
                    self.assertFalse(app.ime.engine.context(first)["preedit"])
                    app.push_screen(Palette())
                    await pilot.pause()
                    await pilot.press(*"nihao", "space")
                    self.assertEqual(app.screen.query_one("#filter").value, "你好")
                    self.assertEqual(app.backend.paste.await_count, 1)
                    await app.ime.toggle()
                    await app.ime.toggle_width()
                    await pilot.press("a")
                    self.assertTrue(
                        app.screen.query_one("#filter").value.endswith("ａ")
                    )
            finally:
                app.ime.close()
            self.assertTrue(
                list(Path(directory).glob("cosmos/rime/profiles/*/rime_ice.userdb"))
            )

    async def test_unavailable_engine_keeps_normal_input(self):
        app = Probe()
        app.action_error = AsyncMock()
        with patch(
            "cosmos_tui.features.ime.controller.Rime",
            side_effect=RuntimeError("Rime unavailable"),
        ):
            await app.ime.toggle()
        self.assertFalse(app.ime.enabled)
        app.action_error.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
