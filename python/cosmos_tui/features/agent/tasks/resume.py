"""One-shot native user confirmation; approval also grants the takeover."""

import asyncio
import hashlib
import hmac
import os

from cosmos_tui.features.agent.control import ControlStore

USER_RESUME_ACTIONS = frozenset({"workspace.resume_control", "tasks.resume"})


def challenge(row, controls, key):
    try:
        marker = controls.marker(row["pane"]).stat().st_mtime_ns
    except FileNotFoundError:
        marker = 0
    payload = f"resume-state-v1\n{row['conversation']}\n{row['id']}\n{row['pane']}\n{row['revision']}\n{marker}"
    return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def approval_payload(conversation, identity, pane, revision, state, reason):
    return f"cosmos-resume-v1\n{conversation}\n{identity}\n{pane}\n{revision}\n{state}\n{reason}"


def describe(row, socket):
    key = os.environ.get("COSMOS_AGENT_CONTEXT_KEY")
    if row["state"] == "paused" and key:
        row["resume_challenge"] = challenge(row, ControlStore(socket), key)
    return row


async def confirmed_resume(tools, identity, pane, revision, state, reason, approval):
    store = tools.task_owner()
    key = os.environ.get("COSMOS_AGENT_CONTEXT_KEY", "")
    if not key or not isinstance(approval, str):
        raise PermissionError("Resume requires the native user confirmation dialog")
    if (
        type(revision) is not int
        or not isinstance(reason, str)
        or not 1 <= len(reason) <= 240
        or not reason.isprintable()
        or not isinstance(state, str)
    ):
        raise ValueError("Invalid resume confirmation")
    payload = approval_payload(
        tools.conversation, identity, pane, revision, state, reason
    )
    if not hmac.compare_digest(
        hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest(), approval
    ):
        raise PermissionError("Invalid native resume confirmation")
    # Validate the live workspace/private boundary before changing task state.
    target = await tools.pane(pane)
    controls = ControlStore(tools.backend.argv[2])

    def resume():
        with controls.locked() as records:
            row = store.get(identity)
            if row["conversation"] != tools.conversation or row["pane"] != pane:
                raise PermissionError(
                    "Resume belongs to another conversation or terminal"
                )
            if (
                row["state"] != "paused"
                or row["revision"] != revision
                or not hmac.compare_digest(challenge(row, controls, key), state)
            ):
                raise ValueError(
                    "Pause state changed; list_tasks and request a fresh confirmation"
                )
            if str(target["pid"]) != row["server_pid"]:
                raise ValueError(
                    "Workspace service changed; rebind the task target explicitly"
                )
            current = records.get(pane)
            if current and (
                current.get("conversation") != tools.conversation
                or current["state"] != "paused"
            ):
                raise ValueError(
                    "Terminal control changed; request a fresh confirmation"
                )
            store.resume_selected(identity, tools.conversation, revision)
            # Human input publishes its marker before waiting on this lock.
            if not hmac.compare_digest(challenge(row, controls, key), state):
                store.pause(tools.conversation)
                raise ValueError("Manual input cancelled this resume confirmation")
            if current:
                current.update(
                    state="ready",
                    token=None,
                    pointer=None,
                    owner=tools.owner,
                    runtime_id=tools.runtime_id,
                )
            controls.marker(pane).unlink(missing_ok=True)
        old_token = tools.control_tokens.pop(pane, None)
        tools.control_geometry.pop(old_token, None)
        return dict(
            resumed=True,
            task_id=identity,
            pane=pane,
            state="ready",
            input_ownership=False,
            next="Observe again, then acquire fresh terminal control",
            task_complete=False,
        )

    # No scheduler wake is queued: this explicit chat turn continues the task itself.
    result = await asyncio.to_thread(resume)
    try:
        observed = await tools.observe(pane, ["text"])
        lease = await tools.acquire_control(
            pane, observed["snapshot_id"], "Resume terminal control"
        )
    except (OSError, RuntimeError, ValueError) as error:
        result.update(
            input_ownership=False,
            error=str(error),
            next="Observe again and acquire control with a fresh observation",
        )
        return result
    result.update(
        state="active",
        input_ownership=True,
        token=lease["token"],
        task=lease["task"],
        task_id=identity,
        control_task_id=lease["task_id"],
        snapshot_id=lease["snapshot_id"],
        dimensions=lease["dimensions"],
        next="Continue with cosmos_step; this resume confirmation approved the takeover",
    )
    return result
