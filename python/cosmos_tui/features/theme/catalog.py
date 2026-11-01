"""Discover terminal and interface themes from TOML files at runtime.

Built-in files live in ``themes/`` beside the executable; user files live in
``$XDG_CONFIG_HOME/cosmos/themes``.  Files use their stem as the configuration
id, so adding or editing a file never requires rebuilding Cosmos.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from pathlib import Path
import tomllib

from cosmos_tui.core.paths import BUILTIN_THEME_DIR, user_theme_dir
from cosmos_tui.ui.logo import DEFAULT_LOGO, LogoStyle
from cosmos_tui.ui.styles import DARK

HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
ROLES = ("bg", "base", "fg", "mute", "acc", "accl", "on")


@dataclass(frozen=True)
class TerminalTheme:
    id: str
    name: str
    fg: str
    bg: str
    ansi: tuple[str, ...] | None
    order: int = 1000


@dataclass(frozen=True)
class CosmosTheme:
    id: str
    name: str
    palette: dict
    light: bool
    logo: LogoStyle
    order: int = 1000


@dataclass(frozen=True)
class Catalog:
    terminals: tuple[TerminalTheme, ...]
    interfaces: tuple[CosmosTheme, ...]
    errors: tuple[str, ...]


INHERIT = TerminalTheme("inherit", "Follow terminal", "default", "default", None, 0)
FALLBACK = CosmosTheme("dark", "Cosmos Dark", dict(DARK), False, DEFAULT_LOGO, 0)
_catalog: Catalog | None = None


def theme_dirs():
    return BUILTIN_THEME_DIR, user_theme_dir()


def _color(value, field):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(f"{field} must be #RRGGBB")
    return value.lower()


def _name(data, theme_id):
    value = data.get("name", theme_id.replace("-", " ").title())
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 64
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("name must be a short printable string")
    return value.strip()


def _order(data):
    value = data.get("order", 1000)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10000:
        raise ValueError("order must be an integer between 0 and 10000")
    return value


def _logo(data, field="logo"):
    value = data.get(field, {})
    if not isinstance(value, dict):
        raise ValueError("logo must be a table")
    foreground = value.get("foreground", DEFAULT_LOGO.foreground)
    background = value.get("background", DEFAULT_LOGO.background)
    colors = {}
    for name, values in (("foreground", foreground), ("background", background)):
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError(f"logo.{name} must contain two colors")
        colors[name] = tuple(_color(color, f"logo.{name}") for color in values)
    mode = value.get("mode", DEFAULT_LOGO.mode)
    steps = value.get("steps", DEFAULT_LOGO.steps)
    if mode not in ("vertical", "horizontal", "diagonal", "radial"):
        raise ValueError("logo.mode must be vertical, horizontal, diagonal or radial")
    if not isinstance(steps, int) or isinstance(steps, bool) or not 2 <= steps <= 256:
        raise ValueError("logo.steps must be between 2 and 256")
    return LogoStyle(colors["foreground"], colors["background"], mode, steps)


def _terminal(path, data):
    theme_id = path.stem
    if theme_id == "inherit":
        raise ValueError("inherit is reserved")
    fg = _color(data.get("fg"), "fg")
    bg = _color(data.get("bg"), "bg")
    ansi = data.get("ansi")
    if not isinstance(ansi, list) or len(ansi) != 16:
        raise ValueError("ansi must contain 16 colors")
    return TerminalTheme(
        theme_id,
        _name(data, theme_id),
        fg,
        bg,
        tuple(_color(color, f"ansi[{index}]") for index, color in enumerate(ansi)),
        _order(data),
    )


def _cosmos(path, data):
    theme_id = path.stem
    colors = data.get("colors")
    if not isinstance(colors, dict):
        raise ValueError("colors table is required")
    palette = {role: _color(colors.get(role), "colors." + role) for role in ROLES}
    light = data.get("light", False)
    if not isinstance(light, bool):
        raise ValueError("light must be true or false")
    return CosmosTheme(
        theme_id,
        _name(data, theme_id),
        palette,
        light,
        _logo(data),
        _order(data),
    )


def _load(path):
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        return None, f"{path.name}: {error}"
    kind = data.get("kind")
    if kind not in ("terminal", "cosmos"):
        return None, f"{path.name}: kind must be terminal or cosmos"
    if not ID.fullmatch(path.stem):
        return None, f"{path.name}: file name must be a safe theme id"
    try:
        return (kind, _terminal(path, data) if kind == "terminal" else _cosmos(path, data)), None
    except ValueError as error:
        return None, f"{path.name}: {error}"


def _files(folder):
    try:
        return [path for path in sorted(folder.glob("*.toml")) if path.is_file()], None
    except OSError as error:
        return None, f"{folder}: {error}"


def reload_themes() -> Catalog:
    """Rescan built-in and user directories and replace the process cache."""
    global _catalog
    builtin, user = theme_dirs()
    terminals = {}
    interfaces = {}
    errors = []
    try:
        user.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        errors.append(f"{user}: {error}")
    for folder in (builtin, user):
        paths, error = _files(folder)
        if error:
            errors.append(error)
            continue
        for path in paths:
            loaded, error = _load(path)
            if error:
                errors.append(error)
                logging.getLogger(__name__).warning("theme ignored: %s", error)
                continue
            kind, theme = loaded
            (terminals if kind == "terminal" else interfaces)[theme.id] = theme
    catalog = Catalog(
        (INHERIT,)
        + tuple(sorted(terminals.values(), key=lambda t: (t.order, t.name.casefold(), t.id))),
        tuple(
            sorted(
                interfaces.values(), key=lambda t: (t.order, t.name.casefold(), t.id)
            )
        ),
        tuple(errors),
    )
    _catalog = catalog
    return catalog


def catalog() -> Catalog:
    return _catalog or reload_themes()


def terminal_theme(theme_id):
    return next((theme for theme in catalog().terminals if theme.id == theme_id), None)


def cosmos_theme(theme_id):
    found = next(
        (theme for theme in catalog().interfaces if theme.id == theme_id), None
    )
    if found:
        return found
    return next(
        (theme for theme in catalog().interfaces if theme.id == "dark"),
        catalog().interfaces[0] if catalog().interfaces else FALLBACK,
    )


def errors():
    return catalog().errors


def terminal_choices():
    return [(theme.id, theme.name) for theme in catalog().terminals]


def cosmos_choices():
    return [(theme.id, theme.name) for theme in catalog().interfaces]
