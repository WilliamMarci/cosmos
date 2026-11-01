"""A dead Tmux control connection exits cleanly instead of crashing input."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cosmos_tui.app import Cosmos


class TerminalEOFGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_key_input_detaches_after_control_connection_ends(self):
        app = object.__new__(Cosmos)
        app.inputs = SimpleNamespace(
            on_key=AsyncMock(side_effect=EOFError("terminal session ended"))
        )
        app.runtime = SimpleNamespace(detach=AsyncMock(return_value=None))
        event = object()

        self.assertIsNone(await Cosmos.on_key(app, event))
        app.inputs.on_key.assert_awaited_once_with(event)
        app.runtime.detach.assert_awaited_once_with("exit")

    async def test_paste_and_mouse_are_guarded_too(self):
        app = object.__new__(Cosmos)
        app.inputs = SimpleNamespace(
            on_paste=AsyncMock(side_effect=EOFError("terminal session ended"))
        )
        app.pointer = SimpleNamespace(
            on_mouse_down=AsyncMock(side_effect=EOFError("terminal session ended"))
        )
        app.runtime = SimpleNamespace(detach=AsyncMock(return_value=None))
        event = object()

        self.assertIsNone(await Cosmos.on_paste(app, event))
        self.assertIsNone(await Cosmos.on_mouse_down(app, event))
        self.assertEqual(app.runtime.detach.await_count, 2)


if __name__ == "__main__":
    unittest.main()
