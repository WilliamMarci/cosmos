"""Install the Cosmos Agent theme once; keep later user theme selections."""

import json
import os

from cosmos_tui.core.paths import ASSET_DIR
from cosmos_tui.features.agent.profile import profile_root, write_private_json


def install_theme():
    root = profile_root()
    theme = root / "themes/cosmos.json"
    if not theme.exists():
        write_private_json(
            theme, json.loads((ASSET_DIR / "agent-cosmos.json").read_text())
        )
    cli = root / "cli.json"
    value = json.loads(cli.read_text()) if cli.exists() else {}
    if "theme" not in value:
        value["theme"] = {"name": "cosmos", "mode": "dark"}
        temporary = root / "cli.json.cosmos-tmp"
        write_private_json(temporary, value)
        os.replace(temporary, cli)
