"""Installation choices are immutable app data, not user/global configuration."""
import json
from cosmos_tui.core.paths import PROJECT_ROOT


def enabled(name):
    manifest = PROJECT_ROOT / "installed-features.json"
    if not manifest.is_file():
        return True  # Source development retains all capabilities.
    return name in json.loads(manifest.read_text())["features"]
