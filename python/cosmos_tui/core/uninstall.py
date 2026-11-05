"""Remove only this marked release installation and its own command link."""

import json
import os
from pathlib import Path
import shutil
import signal
import time

from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.core import lifecycle
from cosmos_tui.terminal.backend import identity


def processes(root):
    found = []
    for folder in Path("/proc").glob("[0-9]*"):
        try:
            info = identity(folder.name)
            if info["pid"] == os.getpid() or info["uid"] != os.getuid():
                continue
            executable = Path(info["executable"].removesuffix(" (deleted)"))
            # Include interpreters using this tree, not arbitrary similarly named apps.
            owned = executable.is_relative_to(root)
            if not owned:
                maps = (folder / "maps").read_text()
                owned = any(line.split(maxsplit=5)[-1].removesuffix(" (deleted)").startswith(str(root) + "/") for line in maps.splitlines() if len(line.split(maxsplit=5)) == 6)
            if owned:
                found.append(info)
        except (OSError, ValueError):
            continue
    return found


def uninstall(yes=False):
    root = PROJECT_ROOT.resolve()
    marker = root / "installed-features.json"
    if root == Path.home().resolve() or root == Path("/") or not marker.is_file() or (root / ".git").exists():
        raise ValueError("Uninstall is available only inside a marked release installation")
    config = json.loads(marker.read_text())
    entry = Path(config["bin_dir"]) / "cosmos"
    items = [item for item in lifecycle.inventory() if Path(item["executable"].removesuffix(" (deleted)")).is_relative_to(root)]
    active = processes(root)
    print("Remove installation:", root)
    if entry.is_symlink() and entry.resolve() == root / "cosmos":
        print("Remove command:", entry)
    lifecycle.preview(items)
    for item in active:
        print(f"  Running PID {item['pid']} · {Path(item['executable']).name}")
    print("Listed installation processes will be stopped; user configuration/cache/state will be kept.")
    lifecycle.confirm(yes, "Stop these processes and uninstall this installation?")
    if items:
        lifecycle.stop_all(items=items, confirmed=True, coordinator=False)
    for item in active:
        try:
            if identity(item["pid"]) == item:
                os.kill(item["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass
    deadline = time.monotonic() + 5
    while processes(root):
        if time.monotonic() >= deadline:
            raise ValueError("Some installation processes did not exit; installation preserved. Close the listed Cosmos clients and rerun uninstall.sh")
        time.sleep(0.1)
    if entry.is_symlink() and entry.resolve() == root / "cosmos":
        entry.unlink()
    shutil.rmtree(root)
    print("Cosmos installation removed; user data retained")
