"""Cross-process pane ownership. Tokens are local capabilities, not model permissions."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile


def location(socket):
    runtime = Path(os.getenv("XDG_RUNTIME_DIR", f"/tmp/cosmos-{os.getuid()}"))
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    if runtime.is_symlink() or runtime.stat().st_uid != os.getuid():
        raise PermissionError("Unsafe Agent runtime directory")
    base = runtime / "cosmos-agent-control"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != os.getuid():
        raise PermissionError("Unsafe Agent control directory")
    base.chmod(0o700)
    return base / (hashlib.sha256(socket.encode()).hexdigest()[:24] + ".json")


class ControlStore:
    def __init__(self, socket):
        self.path = location(socket)

    def marker(self, pane):
        return self.path.with_name(
            self.path.stem
            + "-"
            + hashlib.sha256(pane.encode()).hexdigest()[:16]
            + ".paused"
        )

    def check(self, pane):
        if self.marker(pane).exists():
            raise ValueError("Control paused by user input")

    @contextmanager
    def locked(self):
        descriptor = os.open(
            str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            if os.fstat(descriptor).st_uid != os.getuid():
                raise PermissionError("Unsafe Agent control lock")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if self.path.is_symlink():
                raise PermissionError("Unsafe Agent control state")
            if self.path.exists() and self.path.stat().st_uid != os.getuid():
                raise PermissionError("Agent control state belongs to another user")
            state = json.loads(self.path.read_text()) if self.path.exists() else {}
            if not isinstance(state, dict) or any(
                not isinstance(value, dict)
                or not {"owner", "task", "token", "state"} <= value.keys()
                for value in state.values()
            ):
                raise ValueError("Invalid Agent control state")
            yield state
            fd, temporary = tempfile.mkstemp(dir=self.path.parent)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(state, stream)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        finally:
            os.close(descriptor)

    def acquire(self, pane, owner, task):
        with self.locked() as state:
            self.check(pane)
            current = state.get(pane)
            if current and (current["owner"] != owner or current["state"] == "paused"):
                raise ValueError("Pane already controlled or manually paused")
            token = secrets.token_urlsafe(32)
            state[pane] = dict(owner=owner, task=task, token=token, state="active")
            return dict(pane=pane, token=token, state="active", task=task)

    def change(self, pane, action):
        if not self.path.exists():
            return None
        if action == "pause" and pane in json.loads(self.path.read_text()):
            # Publish revocation before waiting for an in-flight sender's lock.
            descriptor = os.open(
                self.marker(pane), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
            )
            os.close(descriptor)
        with self.locked() as state:
            current = state.get(pane)
            if current is None:
                if action in ("cancel", "resume"):
                    self.marker(pane).unlink(missing_ok=True)
                return None
            changed = action != "pause" or current["state"] != "paused"
            if action == "pause":
                current["state"] = "paused"
            elif action == "resume":
                current["state"] = "ready"
                current["token"] = None
                self.marker(pane).unlink(missing_ok=True)
            elif action == "cancel":
                del state[pane]
                self.marker(pane).unlink(missing_ok=True)
            else:
                raise ValueError("Unknown control state action")
            return dict(
                pane=pane,
                state=current["state"] if action != "cancel" else "ended",
                changed=changed,
            )

    def status(self):
        if not self.path.exists():
            return []
        with self.locked() as state:
            return [
                dict(pane=pane, state=value["state"], task=value["task"])
                for pane, value in state.items()
            ]

    def release(self, pane, owner, token):
        with self.locked() as state:
            current = state.get(pane)
            if current and current["owner"] == owner and current["token"] == token:
                del state[pane]
                self.marker(pane).unlink(missing_ok=True)
                return dict(pane=pane, state="ended")
            raise ValueError("Stale control token")

    def guarded(self, pane, owner, token, operation):
        """Serialize validation and input delivery against manual revocation."""
        with self.locked() as state:
            self.check(pane)
            current = state.get(pane)
            if (
                not current
                or current["owner"] != owner
                or current["token"] != token
                or current["state"] != "active"
            ):
                raise ValueError(
                    "Control revoked; fresh observation and user resume may be required"
                )
            return operation()

    def legacy_guarded(self, pane, operation):
        with self.locked() as state:
            self.check(pane)
            if pane in state:
                raise ValueError(
                    "Pane has a control task; use control_input with its active token"
                )
            return operation()


async def human_input(app, pane):
    import asyncio

    if pane is None:
        return
    store = ControlStore(app.backend.argv[2])
    result = await asyncio.to_thread(store.change, pane.id, "pause")
    if result and result["changed"]:
        try:
            await app.notification_events.publish(
                "Agent control paused · manual input",
                source="agent-control",
                level="info",
            )
        except (OSError, RuntimeError, TimeoutError):
            import logging

            logging.getLogger(__name__).warning(
                "Could not publish manual control pause"
            )
