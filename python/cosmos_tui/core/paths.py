"""Locations derived from the installed package, never from the caller cwd."""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
ASSET_DIR = PACKAGE_ROOT / "assets"
BUILTIN_THEME_DIR = PROJECT_ROOT / "themes"


def config_home():
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def user_theme_dir():
    return config_home() / "cosmos" / "themes"
