"""Explicit preview and shutdown of verified Cosmos backends only."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys

from cosmos_tui.terminal import backend


def inventory():
    # Register a previously installed bundled backend, but never adopt system tmux.
    backend.record()
    result = []
    for path in sorted(backend.records_dir().glob("*.json")):
        item = backend.verified(path)
        if item is None:
            path.unlink(missing_ok=True)
            continue
        output = subprocess.run([backend.executable(), "-S", item["socket"], "list-panes", "-a", "-F", "#{session_name}\t#{window_index}:#{pane_index}\t#{pane_current_command}"], check=True, capture_output=True, text=True, timeout=5)
        item["panes"] = output.stdout.splitlines()
        item["record"] = path
        result.append(item)
    return result


def preview(items):
    from cosmos_tui.features.agent.monitor.storage import Watches
    from cosmos_tui.features.agent.tasks.storage import Tasks

    for item in items:
        print(f"Backend {item['name']} · PID {item['pid']} · {item['socket']}")
        for pane in item["panes"]:
            print("  " + pane)
        tasks = Tasks(item["name"])
        if tasks.path.exists():
            for task in tasks.list():
                if task["state"] not in ("cancelled", "succeeded", "failed"):
                    print(f"  Task {task['id']} · {task['state']}")
        watches = Watches(item["name"])
        if watches.path.exists():
            for watch in watches.list(pending=True):
                print(f"  Watch {watch['id']} · {watch['kind']}")


def confirm(yes=False, question="End the listed Cosmos sessions and tasks?"):
    if yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("Confirmation requires a terminal; use --yes after reviewing the affected sessions/tasks")
    if input(question + " [y/N] ").strip().lower() not in ("y", "yes"):
        raise ValueError("Cancelled; no sessions were stopped")


def stop_services(socket):
    from cosmos_tui.features.agent.monitor.service import suspend
    from cosmos_tui.features.agent.tasks.service import suspend as suspend_tasks

    suspend(socket)
    suspend_tasks(socket)
    from cosmos_tui.features.agent.tasks.storage import Tasks
    from cosmos_tui.features.agent.monitor.storage import Watches

    tasks = Tasks(socket)
    if tasks.path.exists():
        for task in tasks.list():
            if task["state"] not in ("cancelled", "succeeded", "failed"):
                tasks.change(task["id"], state="cancelled", next_run=None, pending=None)
    watches = Watches(socket)
    if watches.path.exists():
        for watch in watches.list(pending=True):
            watches.finish(watch["id"], "invalidated", dict(type="backend_stopped"))


async def stop_coordinator():
    from cosmos_tui.core import rpc

    try:
        await rpc.call("daemon.shutdown", {})
    except (FileNotFoundError, ConnectionRefusedError):
        pass


def stop_all(yes=False, *, items=None, confirmed=False, coordinator=True):
    items = inventory() if items is None else items
    if not confirmed:
        preview(items)
        print("The Cosmos coordinator and managed Mods will also stop.")
        confirm(yes)
    # Revalidate *all* records before any destructive action.
    for item in items:
        if backend.verified(item["record"]) is None:
            raise ValueError("Backend exited during confirmation; run stop --all again")
    for item in items:
        stop_services(item["name"])
    if coordinator:
        asyncio.run(stop_coordinator())
    for item in items:
        if backend.verified(item["record"]) is not None:
            subprocess.run([backend.executable(), "-S", item["socket"], "kill-server"], check=True, timeout=5)
        item["record"].unlink(missing_ok=True)
    print("Cosmos backends stopped; user configuration and state retained")
