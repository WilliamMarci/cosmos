"""Watch registration/worker exit handoff, independent of UI and model lifetime."""

from contextlib import contextmanager
import fcntl
import os
import subprocess
import sys
import threading

from cosmos_tui.core.paths import PROJECT_ROOT


@contextmanager
def starting(watches):
    fd = os.open(
        str(watches.path) + ".start", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def start(watches, socket):
    """Caller holds starting(); duplicate startup contenders exit without monitoring."""
    fd = os.open(
        str(watches.path) + ".worker", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    finally:
        os.close(fd)
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT / "python"))
    env.pop("COSMOS_AGENT_API_KEY", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "cosmos_tui.features.agent.monitor.worker", socket],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    threading.Thread(target=process.wait, daemon=True).start()


def recover(socket):
    from cosmos_tui.features.agent.monitor.storage import Watches

    watches = Watches(socket)
    if not watches.path.exists():
        return
    with starting(watches):
        if watches.list(pending=True):
            start(watches, socket)


def suspend(socket):
    from cosmos_tui.features.agent.monitor.storage import Watches

    watches = Watches(socket)
    if not watches.path.exists():
        return
    with starting(watches):
        descriptor = os.open(
            watches.path.with_suffix(".suspended"),
            os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        os.close(descriptor)
