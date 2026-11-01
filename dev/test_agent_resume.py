"""Native resume confirmation is one-shot and never restores old input authority."""

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from cosmos_tui.features.agent.control import ControlStore
from cosmos_tui.features.agent.tasks.resume import approval_payload
from cosmos_tui.features.agent.tasks.storage import Tasks
from cosmos_tui.features.agent.terminal import TerminalTools

KEY = "resume-fixture-key"
PANE = dict(pane_id="%4", pid=1234, session_id="$1")


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict(
            os.environ,
            COSMOS_TASKS_HOME=temporary.name + "/tasks",
            XDG_RUNTIME_DIR=temporary.name + "/run",
            COSMOS_AGENT_CONTEXT_KEY=KEY,
        )
        env.start()
        self.addCleanup(env.stop)
        service = patch("cosmos_tui.features.agent.tasks.service.start")
        service.start()
        self.addCleanup(service.stop)
        self.tools = TerminalTools("fixture")
        self.tools.conversation = "ses_fixture"
        self.tools.runtime_id = "runtime"
        self.tools.pane = AsyncMock(return_value=PANE)
        self.tools.observe = AsyncMock(
            return_value=dict(
                snapshot_id="fresh", dimensions=dict(width=80, height=24)
            )
        )
        self.tools.acquire_control = AsyncMock(
            return_value=dict(
                token="takeover-token",
                task="Resume task",
                task_id="control_task",
                snapshot_id="fresh",
                dimensions=dict(width=80, height=24),
            )
        )
        self.store = Tasks("fixture")
        self.row = self.store.create(
            "ses_fixture", "runtime", PANE, "Continue requested work", kind="schedule"
        )
        self.controls = ControlStore("fixture")
        self.lease = self.controls.acquire(
            "%4",
            self.tools.owner,
            "Task",
            conversation="ses_fixture",
            logical_task=self.row["id"],
        )
        self.controls.change("%4", "pause")
        self.store.pause("ses_fixture")

    async def request(self):
        row = next(
            r for r in await self.tools.list_tasks() if r["id"] == self.row["id"]
        )
        args = dict(
            id=row["id"],
            pane=row["pane"],
            revision=row["revision"],
            resume_challenge=row["resume_challenge"],
            reason="Continue the user's requested task",
        )
        payload = approval_payload(
            self.tools.conversation,
            args["id"],
            args["pane"],
            args["revision"],
            args["resume_challenge"],
            args["reason"],
        )
        return args, hmac.new(
            KEY.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    async def test_confirmation_resumes_only_selected_task_without_old_token_or_extra_wake(
        self,
    ):
        other = self.store.create(
            "ses_fixture", "runtime", dict(PANE, pane_id="%5"), "Other task"
        )
        self.store.pause("ses_fixture")
        args, proof = await self.request()
        result = await self.tools.request_resume(**args, _cosmos_resume_approval=proof)
        self.assertTrue(result["resumed"])
        self.assertTrue(result["input_ownership"])
        self.assertEqual(result["token"], "takeover-token")
        row = self.store.get(self.row["id"])
        self.assertEqual(row["state"], "running")
        self.assertIsNone(row["pending"])
        self.assertEqual(self.store.get(other["id"])["state"], "paused")
        with self.assertRaises(ValueError):
            self.controls.guarded(
                "%4", self.tools.owner, self.lease["token"], lambda: None
            )
        with self.assertRaises(ValueError):
            await self.tools.request_resume(**args, _cosmos_resume_approval=proof)

    async def test_unsigned_tampered_and_stale_confirmations_keep_pause(self):
        args, proof = await self.request()
        with self.assertRaises(PermissionError):
            await self.tools.request_resume(**args)
        with self.assertRaises(PermissionError):
            await self.tools.request_resume(
                **dict(args, reason="Changed request"), _cosmos_resume_approval=proof
            )
        self.controls.change("%4", "pause")
        with self.assertRaises(ValueError):
            await self.tools.request_resume(**args, _cosmos_resume_approval=proof)
        self.assertTrue(self.store.paused("ses_fixture"))
        self.assertEqual(self.controls.status()[0]["state"], "paused")

    async def test_confirmed_reconnect_rebinds_ready_owner_without_reusing_token(self):
        with self.controls.locked() as records:
            records["%4"]["owner"] = "old-runtime-owner"
        args, proof = await self.request()
        result = await self.tools.request_resume(**args, _cosmos_resume_approval=proof)
        self.assertEqual(result["token"], "takeover-token")
        with self.controls.locked(write=False) as records:
            self.assertEqual(records["%4"]["owner"], self.tools.owner)
            self.assertIsNone(records["%4"]["token"])

    async def test_new_manual_input_and_replaced_service_invalidate_approval(self):
        args, proof = await self.request()
        from cosmos_tui.features.agent.tasks.lifecycle import pause_target

        pause_target("fixture", "%4")
        with self.assertRaises(ValueError):
            await self.tools.request_resume(**args, _cosmos_resume_approval=proof)
        args, proof = await self.request()
        self.tools.pane.return_value = dict(PANE, pid=999999)
        with self.assertRaises(ValueError):
            await self.tools.request_resume(**args, _cosmos_resume_approval=proof)
        self.assertTrue(self.store.paused("ses_fixture"))

    async def test_authenticated_mcp_dispatch_requires_and_consumes_native_approval(
        self,
    ):
        from cosmos_tui.features.agent.mcp import dispatch

        self.tools._conversations = {"ses_fixture": self.tools}
        args, proof = await self.request()
        context = dict(
            session="ses_fixture",
            signature=hmac.new(
                KEY.encode(), b"ses_fixture", hashlib.sha256
            ).hexdigest(),
        )
        request = dict(
            method="tools/call",
            params=dict(
                name="request_resume", arguments=dict(args, _cosmos_context=context)
            ),
        )
        denied = await dispatch(self.tools, request)
        self.assertTrue(denied["isError"])
        self.assertTrue(self.store.paused("ses_fixture"))
        request["params"]["arguments"]["_cosmos_resume_approval"] = proof
        accepted = await dispatch(self.tools, request)
        self.assertFalse(accepted["isError"])
        self.assertTrue(json.loads(accepted["content"][0]["text"])["resumed"])

    async def test_generic_actions_cannot_bypass_resume_confirmation(self):
        from cosmos_tui.features.agent.actions import ActionTools
        from cosmos_tui.features.agent.action_ui import catalog
        from types import SimpleNamespace

        actions = ActionTools("fixture")
        actions.ui_call = AsyncMock()
        for identity in ("workspace.resume_control", "tasks.resume"):
            with self.assertRaises(PermissionError):
                await actions.invoke_action(identity, "ui")
        actions.ui_call.assert_not_awaited()
        for context in ("workspace", "tasks"):
            app = SimpleNamespace(
                client="fixture", key_context=lambda: context, active=lambda: None
            )
            identities = {r["id"] for r in catalog(app)["actions"]}
            self.assertNotIn("workspace.resume_control", identities)
            self.assertNotIn("tasks.resume", identities)
        self.assertTrue(self.store.paused("ses_fixture"))

    async def test_private_target_refusal_does_not_clear_pause(self):
        args, proof = await self.request()
        self.tools.pane.side_effect = PermissionError("Private pane")
        with self.assertRaises(PermissionError):
            await self.tools.request_resume(**args, _cosmos_resume_approval=proof)
        self.assertTrue(self.store.paused("ses_fixture"))


if __name__ == "__main__":
    unittest.main()
