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


def display_path(value):
    """Abbreviate HOME and its symlink aliases for display only."""
    if not value or not Path(value).is_absolute():
        return value
    home = Path(os.path.abspath(os.path.expanduser("~")))
    path = Path(os.path.normpath(value))
    try:
        relative = path.relative_to(home)
    except ValueError:
        try:
            relative = path.resolve().relative_to(home.resolve())
        except (ValueError, OSError, RuntimeError):
            return value
    return "~" if relative == Path(".") else "~/" + relative.as_posix()
