"""Explicit, non-overwriting migration of earlier Cosmos-only Agent data."""

import os
from pathlib import Path
import shutil

from cosmos_tui.features.agent.profile import (
    initialize_profile,
    private_directory,
    secure_profile,
)


def migrate():
    root = initialize_profile()
    home = Path.home()
    candidates = [(root.parent / "skills", root / "skills")]
    for variable, fallback, destination in (
        ("XDG_DATA_HOME", home / ".local/share", "data"),
        ("XDG_CACHE_HOME", home / ".cache", "cache"),
        ("XDG_STATE_HOME", home / ".local/state", "state"),
    ):
        source = Path(os.getenv(variable, str(fallback))) / "cosmos/agent/opencode"
        candidates.append((source, root / destination / "opencode"))
    plan = [(source, target) for source, target in candidates if source.exists()]
    for source, target in plan:
        if source.is_symlink() or any(p.is_symlink() for p in source.rglob("*")):
            raise ValueError(
                f"Resolve legacy profile symlinks before migrating: {source}"
            )
        if target.exists():
            raise ValueError(f"Migration will not overwrite {target}")
    moved = []
    try:
        for source, target in plan:
            private_directory(target.parent)
            shutil.move(str(source), str(target))
            moved.append((source, target))
        secure_profile()
    except Exception:
        for source, target in reversed(moved):
            shutil.move(str(target), str(source))
        raise
    return [str(target) for _, target in moved]
