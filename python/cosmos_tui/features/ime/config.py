"""Discover existing desktop Rime data before the Cosmos fallback."""

import os
from pathlib import Path
import re
from cosmos_tui.core.paths import PROJECT_ROOT


def configuration():
    config = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    explicit = os.getenv("COSMOS_RIME_DATA")
    choices = (
        [Path(explicit).expanduser()]
        if explicit
        else [
            config / "ibus/rime",
            config / "fcitx5/rime",
            config / "fcitx/rime",
            config / "cosmos/rime",
            PROJECT_ROOT / "share/rime-data",
        ]
    )
    source = next((p for p in choices if p.is_dir()), choices[0])
    schema = os.getenv("COSMOS_RIME_SCHEMA")
    if not schema:
        user = source / "user.yaml"
        if user.exists():
            match = re.search(
                r'previously_(?:selected|used)_schema:\s*["\']?([A-Za-z0-9_-]+)',
                user.read_text(errors="replace"),
            )
            if match:
                schema = match[1]
    if not schema and (source / "build/rime_ice.schema.yaml").exists():
        schema = "rime_ice"
    if not schema:
        for file in (source / "build/default.yaml", source / "default.yaml"):
            if file.exists():
                match = re.search(
                    r'schema:\s*["\']?([A-Za-z0-9_-]+)',
                    file.read_text(errors="replace"),
                )
                if match:
                    schema = match[1]
                    break
    schema = schema or "rime_ice"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", schema):
        raise RuntimeError("Invalid Rime schema ID")
    if not (source / f"build/{schema}.schema.yaml").exists():
        raise RuntimeError(
            f"Compiled {schema} data not found in {source}; set COSMOS_RIME_DATA or configure cosmos/rime"
        )
    return source, schema
