"""Revocation precedes UI input and invalidates queued Agent operations."""

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import AsyncMock, patch

from cosmos_tui.features.agent.control import ControlStore
from test_navigation import Probe


class ControlStoreTests(unittest.TestCase):
    def test_revoke_inflight_before_delivery_and_cancel_keeps_no_token(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_RUNTIME_DIR=directory),
        ):
            store = ControlStore("test-service")
            lease = store.acquire("%7", "owner", "Task")
            started, proceed = threading.Event(), threading.Event()
            delivered = []

            def sending():
                started.set()
                self.assertTrue(proceed.wait(2))
                store.check("%7")
                delivered.append(True)

            with ThreadPoolExecutor(max_workers=2) as executor:
                pending = executor.submit(
                    store.guarded, "%7", "owner", lease["token"], sending
                )
                self.assertTrue(started.wait(2))
                pause = executor.submit(store.change, "%7", "pause")
                for _ in range(200):
                    if store.marker("%7").exists():
                        break
                    threading.Event().wait(0.005)
                self.assertTrue(store.marker("%7").exists())
                proceed.set()
                with self.assertRaises(ValueError):
                    pending.result(timeout=2)
                self.assertEqual(pause.result(timeout=2)["state"], "paused")
            self.assertEqual(delivered, [])
            self.assertNotIn("token", store.status()[0])
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            store.change("%7", "cancel")
            self.assertEqual(store.status(), [])
            with self.assertRaises(ValueError):
                store.guarded("%7", "owner", lease["token"], lambda: None)


class ControlUITests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_key_and_paste_pause_before_forwarding(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_RUNTIME_DIR=directory),
        ):
            app = Probe()
            async with app.run_test(size=(100, 30)) as pilot:
                store = ControlStore(app.backend.argv[2])
                store.acquire("%0", "fixture-owner", "Task")

                async def sent(*args):
                    self.assertEqual(store.status()[0]["state"], "paused")

                app.notification_events.publish = AsyncMock()
                app.backend.send = AsyncMock(side_effect=sent)
                app.ime.handle = AsyncMock(return_value=False)
                await pilot.press("a")
                app.backend.send.assert_awaited()
                store.change("%0", "resume")
                app.backend.paste = AsyncMock(side_effect=sent)
                from textual import events

                await app.inputs.on_paste(events.Paste("manual paste"))
                app.backend.paste.assert_awaited_once_with("manual paste")

    async def test_header_click_pauses_without_application_mouse_input(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_RUNTIME_DIR=directory),
        ):
            app = Probe()
            async with app.run_test(size=(100, 30)) as pilot:
                app.panes[0].y = 1
                app._agent_headers = {"%0": dict(state="active", task="Task")}
                store = ControlStore(app.backend.argv[2])
                store.acquire("%0", "fixture-owner", "Task")
                app.notification_events.publish = AsyncMock()
                app.backend.send_bytes = AsyncMock()
                await pilot.click("#terminal", offset=(1, 0))
                self.assertEqual(store.status()[0]["state"], "paused")
                app.backend.send_bytes.assert_not_awaited()
