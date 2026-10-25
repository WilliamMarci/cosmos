"""File categories and metadata rendered through Cosmos semantic roles."""

import stat
from pathlib import Path
from rich.text import Text
from cosmos_tui.ui.theme import SEMANTIC_COLORS, blend


def category(item):
    if item["link"]:
        return "link"
    if item["directory"]:
        return "directory"
    if item.get("mode", 0) & 0o111:
        return "executable"
    suffix = Path(item["name"]).suffix.lower()
    for kind, extensions in {
        "image": ".png .jpg .jpeg .webp .gif .svg .ico .bmp .avif",
        "document": ".pdf .epub .md .markdown .html .htm .txt .docx",
        "archive": ".zip .gz .xz .bz2 .tar .7z .rar .zst",
        "media": ".mp4 .mkv .webm .mp3 .flac .wav .ogg",
        "code": ".py .rs .c .h .cpp .js .ts .json .toml .yaml .sh",
    }.items():
        if suffix in extensions.split():
            return kind
    return "file"


def appearance(item, palette):
    kind = category(item)
    role, icon = {
        "link": ("warning", "󰌷"),
        "directory": ("accl", "󰉋"),
        "executable": ("success", "󰆍"),
        "image": ("success", "󰋩"),
        "document": ("fg", "󰈙"),
        "archive": ("error", "󰀼"),
        "media": ("warning", "󰎆"),
        "code": ("accl", "󰅩"),
        "file": ("mute", "󰈔"),
    }[kind]
    color = palette.get(
        "files." + kind, palette.get(role, SEMANTIC_COLORS.get(role, palette["accl"]))
    )
    if item["name"].startswith("."):
        color = blend(color, palette["bg"], 0.3)
    return color, icon


def size_label(size):
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024


def metadata(items, cursor):
    if not items:
        return dict(name="Empty", size="", permissions="", position="0/0", owner="")
    cursor = max(0, min(len(items) - 1, cursor))
    item = items[cursor]
    mode = item.get("mode", 0)
    return dict(
        name=item["name"],
        size=size_label(item["size"]),
        permissions=stat.filemode(mode),
        owner=f"{item.get('uid', '')}:{item.get('gid', '')}",
        position=f"{cursor + 1}/{len(items)}",
        percent=f"{round((cursor + 1) / len(items) * 100)}%",
    )


def permission_text(value, palette):
    result = Text()
    for char in value:
        role = {"r": "warning", "w": "error", "x": "success", "-": "mute"}.get(
            char, "accl"
        )
        result.append(
            char, style=palette.get(role, SEMANTIC_COLORS.get(role, palette["accl"]))
        )
    return result
