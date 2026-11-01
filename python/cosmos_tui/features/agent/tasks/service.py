"""One detached scheduler per Tmux service, independent of the current UI."""

import fcntl
import os
import subprocess
import sys
import threading

from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.features.agent.tasks.storage import Tasks


def start(socket, *, resume=False):
    store = Tasks(socket)
    store.purge_controls()
    store.settings()
    if resume:
        store.path.with_suffix(".suspended").unlink(missing_ok=True)
    if store.path.with_suffix(".suspended").exists():
        return
    lock = os.open(
        str(store.path) + ".starting", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        running = os.open(
            str(store.path) + ".worker", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(running, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
        finally:
            os.close(running)
        env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT / "python"))
        env.pop("COSMOS_AGENT_API_KEY", None)
        process = subprocess.Popen(
            [sys.executable, "-m", "cosmos_tui.features.agent.tasks.worker", socket],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        threading.Thread(target=process.wait, daemon=True).start()
    finally:
        os.close(lock)


def recover(socket):
    if Tasks(socket).path.exists():
        start(socket, resume=True)


def suspend(socket):
    store = Tasks(socket)
    if store.path.exists():
        descriptor = os.open(
            store.path.with_suffix(".suspended"),
            os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        os.close(descriptor)
