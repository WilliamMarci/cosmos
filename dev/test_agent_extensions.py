"""Plain fallback and Reader lifecycle events through the actual UI loading path."""

import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
from test_navigation import Probe
from cosmos_tui.features.agent.launch import launch, arguments
from cosmos_tui.features.agent.action_ui import handle


class PlainFallbackTests(unittest.TestCase):
    def test_system_opencode_is_execed_without_profile_or_injected_environment(self):
        with (
            patch(
                "cosmos_tui.features.agent.launch.runtime",
                return_value=(["/usr/bin/opencode"], None),
            ),
            patch(
                "cosmos_tui.features.agent.launch.native_runtime", return_value=False
            ),
            patch("cosmos_tui.features.agent.launch.os.execvp") as execute,
            patch("cosmos_tui.features.agent.launch.initialize_profile") as profile,
            patch("cosmos_tui.features.agent.launch.environment") as environment,
            patch("cosmos_tui.features.agent.launch.os.umask") as umask,
        ):
            self.assertEqual(arguments(None, "%0"), ["/usr/bin/opencode"])
            launch("unused", "%0")
            execute.assert_called_once_with("/usr/bin/opencode", ["/usr/bin/opencode"])
            profile.assert_not_called()
            environment.assert_not_called()
            umask.assert_not_called()
            from cosmos_tui.features.agent.conversations import export_conversation

            with patch(
                "cosmos_tui.features.agent.conversations.initialize_profile"
            ) as private:
                with self.assertRaisesRegex(RuntimeError, "not installed"):
                    export_conversation("ses_fixture")
                private.assert_not_called()


class ReaderLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_loading_success_failure_and_superseded_events(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "good.png"
            Image.new("RGB", (40, 30), "red").save(image)
            bad = Path(directory) / "broken.png"
            bad.write_text("not an image")
            app = Probe()
            app.action_error = AsyncMock()
            app.settings["viewer_prefetch"] = False
            async with app.run_test(size=(80, 24)):
                pane = app.active()
                reader = app.reader_ui

                def opening(path):
                    pane.viewer = base64.b64encode(
                        json.dumps(
                            dict(path=str(path), page=1, zoom=1, pan=[0, 0])
                        ).encode()
                    ).decode()
                    reader.revisions[pane.id] = reader.revisions.get(pane.id, 0) + 1
                    return reader.events.begin(pane, str(path))

                request = opening(image)
                pending = asyncio.create_task(reader.events.result(request, 2000))
                reader.loading.frame(pane)
                await reader.loading.pending[pane.id]
                event = await pending
                self.assertEqual(event["topic"], "reader.loaded")
                self.assertEqual(reader.loading.ready[pane.id][2].source_size, (40, 30))
                with patch(
                    "cosmos_tui.features.agent.terminal.TerminalTools.pane",
                    AsyncMock(return_value={}),
                ):
                    received = await handle(
                        app,
                        dict(
                            client=app.client,
                            operation="reader_events",
                            request_id=request,
                        ),
                    )
                self.assertEqual(received, event)

                request = opening(bad)
                reader.loading.frame(pane)
                await reader.loading.pending[pane.id]
                event = await reader.events.result(request)
                self.assertEqual(event["topic"], "reader.failed")
                self.assertTrue(event["data"]["error"])
                app.action_error.assert_awaited()

                obsolete = opening(image)
                opening(bad)
                self.assertEqual(
                    (await reader.events.result(obsolete))["topic"], "reader.superseded"
                )
                # A completion from an old wire cannot complete its replacement.
                record = reader.events.requests[obsolete]
                reader.events.finish(pane.id, record["wire"], "loaded")
                self.assertEqual(
                    (await reader.events.result(obsolete))["topic"], "reader.superseded"
                )

                # Close during asynchronous preparation: no stale ready event or task crash.
                request = opening(image)
                started, proceed = asyncio.Event(), asyncio.Event()
                ready = reader.loading.ready[pane.id][2]

                async def delayed(_pane):
                    started.set()
                    await proceed.wait()
                    return ready

                previous_ready = reader.loading.ready[pane.id]
                with patch.object(reader, "prepare", side_effect=delayed):
                    reader.loading.frame(pane)
                    task = reader.loading.pending[pane.id]
                    await started.wait()
                    import copy

                    replacement = copy.copy(pane)
                    replacement.viewer = ""
                    app.panes = [
                        replacement if p.id == pane.id else p for p in app.panes
                    ]
                    reader.events.replaced(pane.id, None)
                    proceed.set()
                    await task
                self.assertIs(reader.loading.ready[pane.id], previous_ready)
                self.assertEqual(
                    (await reader.events.result(request))["topic"], "reader.superseded"
                )
            await reader.close()
