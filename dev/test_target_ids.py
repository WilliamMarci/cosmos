"""Stable IDs survive rename and pane indices remain local display coordinates."""

import os
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cosmos_tui.terminal.tmux import Tmux
from cosmos_tui.terminal import sessions, targets


@unittest.skipUnless(os.getenv("COSMOS_TEST_TMUX"), "isolated Tmux integration")
class TargetIDTests(unittest.IsolatedAsyncioTestCase):
    async def test_ids_session_rename_pane_focus_and_history(self):
        with tempfile.TemporaryDirectory(prefix="cosmos-id-test-") as root:
            env = dict(
                HOME=root, COSMOS_TMUX_SOCKET=Path(root).name, COSMOS_RC="/dev/null"
            )
            with patch.dict(os.environ, env):
                sid = await sessions.create("alpha", root)
                backend = Tmux(sid)
                try:
                    await backend.connect()
                    self.assertEqual(backend.session, "alpha")
                    window = (await backend.inventory())[0]
                    await backend.request("split-window -h -t " + window["window_id"])
                    panes = await backend.snapshot()
                    self.assertEqual({p.index for p in panes}, {0, 1})
                    self.assertTrue(
                        all(
                            p.session_id == sid and p.window_id == window["window_id"]
                            for p in panes
                        )
                    )
                    selected = panes[-1]
                    row = dict(window, kind="pane", pane_id=selected.id)
                    await targets.rename(backend, row, "worker")
                    self.assertEqual(
                        next(
                            p.name
                            for p in await backend.snapshot()
                            if p.id == selected.id
                        ),
                        "worker",
                    )
                    await targets.select(backend, row)
                    self.assertEqual(
                        next(p.id for p in await backend.snapshot() if p.active),
                        selected.id,
                    )
                    await sessions.rename(sid, "renamed")
                    self.assertTrue(await sessions.exists(sid))
                    self.assertEqual((await sessions.listing())[0]["id"], sid)
                    self.assertEqual((await sessions.listing())[0]["name"], "renamed")
                    await backend.request(
                        f"send-keys -t {selected.id} 'seq 1 200' Enter"
                    )
                    for _ in range(50):
                        count = await backend.request(
                            f"display-message -p -t {selected.id} '#{{history_size}}'"
                        )
                        if count and int(count[0]) > 0:
                            break
                        await asyncio.sleep(0.02)
                    await backend.request("copy-mode -t " + selected.id)
                    await backend.request(f"send-keys -X -t {selected.id} history-top")
                    copied = next(
                        p for p in await backend.snapshot() if p.id == selected.id
                    )
                    self.assertTrue(copied.copy_mode)
                    self.assertGreater(copied.history_size, 0)
                    self.assertGreater(copied.scroll_position, 0)
                    self.assertLessEqual(
                        copied.history_size
                        - copied.scroll_position
                        + copied.cursor[1]
                        + 1,
                        copied.height,
                    )
                    await backend.request(f"send-keys -X -t {selected.id} cancel")
                    history = await sessions.history(sid, pane=selected.id, lines=5)
                    self.assertEqual(history[0]["session_id"], sid)
                    self.assertEqual(history[0]["pane"], selected.id)
                    await targets.new_window(backend, dict(window, kind="session"))
                    self.assertEqual(len(await backend.inventory()), 2)
                    await targets.split(backend, row, False)
                    self.assertEqual(
                        len(await backend.snapshot(window["window_id"])), 3
                    )
                    with self.assertRaises(ValueError):
                        await Tmux("$999999").connect()
                    with self.assertRaises(ValueError):
                        await sessions.create("$999999")
                finally:
                    await backend.close()
                    await Tmux().cli("kill-server")
