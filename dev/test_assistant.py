"""Cosmos must use terminal_agent's controller without running its tty UI."""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / name)
    for name in ("python", "terminal_agent")
]
from textual.app import App  # noqa: E402
from cosmos_tui.chrome import MiniAction  # noqa: E402
from cosmos_tui.assistant import Assistant  # noqa: E402
from terminal_agent.ui import InlineUI  # noqa: E402
from cosmos_tui.app import Cosmos, TerminalSurface  # noqa: E402
from cosmos_tui.backend import Pane  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.widgets import Static  # noqa: E402


class Probe(App):
    prefix = False
    panes = []

    async def on_mount(self):
        self.result = None
        await self.push_screen(
            Assistant(
                dict(
                    pane="%0",
                    cwd="/tmp",
                    demo=True,
                    state=dict(command="draft", request="convert", cursor=7),
                )
            ),
            self.completed,
        )

    def completed(self, value):
        self.result = value


class LayerProbe(Cosmos):
    async def on_mount(self, event):
        event.prevent_default()
        self._workspace_screen = self.screen
        self.query_one("#agent-powerline").display = False
        self.panes = [Pane("%0", 0, 0, 80, 23, True, [], "", (2, 2))]
        self.lines = {"%0": [Text("SHELL_SENTINEL"), Text("$ existing command")]}
        self.query_one(TerminalSurface).refresh()
        await self.push_screen(
            Assistant(
                dict(
                    pane="%0",
                    cwd="/tmp",
                    demo=True,
                    state=dict(command="existing command", request="draft"),
                )
            )
        )

    async def on_unmount(self, event):
        event.prevent_default()


class AssistantTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_cosmos_css_keeps_shell_visible_and_all_controls_present(self):
        app = LayerProbe()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            self.assertEqual(screen.styles.background.a, 0)
            self.assertEqual(screen.query_one("#assistant-row").region.height, 1)
            self.assertIn("SHELL_SENTINEL", app.export_screenshot())
            self.assertEqual(len(screen.query(MiniAction)), 3)
            for button in screen.query(MiniAction):
                self.assertEqual(button.region.height, 1)
                self.assertEqual(button.content_region.height, 1)
            self.assertIn("ai", app.export_screenshot())
            self.assertEqual(
                screen.query_one("#assistant-indicator", Static).render().plain, " › "
            )
            self.assertFalse(
                screen.query_one("#assistant-confirm", MiniAction).disabled
            )
            self.assertTrue(screen.query_one("#assistant-input").cursor_blink)
            await pilot.click("#assistant-confirm")
            self.assertIs(app.screen, app._workspace_screen)

    async def test_busy_and_error_are_visible_without_replacing_request(self):
        app = LayerProbe()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = app.screen
            started, finish = asyncio.Event(), asyncio.Event()

            async def propose(history):
                started.set()
                await finish.wait()
                raise RuntimeError("Provider unavailable")

            screen.controller.backend.propose = propose
            await pilot.press("enter")
            await started.wait()
            self.assertEqual(screen.controller.state, "busy")
            self.assertNotEqual(
                screen.query_one("#assistant-indicator", Static).render().plain, " › "
            )
            finish.set()
            await pilot.pause()
            self.assertEqual(screen.controller.state, "error")
            self.assertIn("Provider&#160;unavailable", app.export_screenshot())
            self.assertEqual(screen.query_one("#assistant-input").value, "draft")
            self.assertEqual(screen.query_one("#assistant").region.height, 2)

    async def test_reuses_controller_and_native_update_protocol(self):
        app = Probe()
        async with app.run_test() as pilot:
            controller = app.screen.controller
            self.assertIsInstance(controller, InlineUI)
            await pilot.press("enter")
            await pilot.pause(0.3)
            self.assertEqual(app.result["action"], "update")
            self.assertEqual(
                app.result["state"]["command"], "magick '*.png' images.pdf"
            )
            self.assertEqual(
                app.result["state"]["history"],
                [{"request": "convert", "previous_command": "draft"}],
            )

    async def test_tab_and_history_restore_original_draft(self):
        app = Probe()
        async with app.run_test() as pilot:
            app.screen.controller.request_history = ["first", "second"]
            await pilot.press("up")
            self.assertEqual(app.screen.controller.input.text, "second")
            await pilot.press("down")
            self.assertEqual(app.screen.controller.input.text, "convert")
            await pilot.press("tab")
            self.assertEqual(app.result["action"], "edit")
            self.assertEqual(app.result["state"]["command"], "draft")
            self.assertEqual(app.result["state"]["request"], "convert")

    async def test_escape_cancels_generation_and_preserves_command(self):
        app = Probe()
        async with app.run_test() as pilot:
            cancelled = asyncio.Event()

            async def propose(history):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            app.screen.controller.backend.propose = propose
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("escape")
            self.assertTrue(cancelled.is_set())
            self.assertEqual(app.result["action"], "cancel")
            self.assertEqual(app.result["state"]["command"], "draft")


if __name__ == "__main__":
    unittest.main()
