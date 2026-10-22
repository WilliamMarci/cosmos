"""Locations derived from the installed package, never from the caller cwd."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
ASSET_DIR = PACKAGE_ROOT / "assets"
