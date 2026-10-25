"""Directory snapshots and Yazi-native natural ordering, independent of UI."""

import ctypes
from functools import cmp_to_key, lru_cache
import os
from pathlib import Path
from cosmos_tui.core.paths import PROJECT_ROOT


@lru_cache(maxsize=1)
def sorter():
    library = PROJECT_ROOT / ".build/libcosmos_files.so"
    if not library.is_file():
        raise RuntimeError("Build the Cosmos file backend: bash dev/build_files.sh")
    native = ctypes.CDLL(str(library))
    function = native.cosmos_natsort
    function.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    function.restype = ctypes.c_int
    return native, function


def entries(state):
    _, compare = sorter()
    result = []
    query = state.get("filter", "")
    flags = 0 if any(c.isupper() for c in query) else 2
    import re

    pattern = re.compile(re.escape(query), flags)
    with os.scandir(state["path"]) as listing:
        for entry in listing:
            if not state.get("show_hidden") and entry.name.startswith("."):
                continue
            if query and not pattern.search(entry.name):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
                result.append(
                    dict(
                        name=entry.name,
                        path=entry.path,
                        directory=entry.is_dir(),
                        size=info.st_size,
                        mtime=info.st_mtime,
                        link=entry.is_symlink(),
                        mode=info.st_mode,
                        uid=info.st_uid,
                        gid=info.st_gid,
                        target=os.readlink(entry.path) if entry.is_symlink() else "",
                    )
                )
            except FileNotFoundError:
                continue
            if len(result) >= 50000:
                raise ValueError("Directory exceeds 50000 entries; narrow its scope")

    kind = state.get("category", "all")
    if kind != "all":
        from cosmos_tui.features.files.style import category

        result = [item for item in result if category(item) == kind]

    def order(a, b):
        if a["directory"] != b["directory"]:
            return -1 if a["directory"] else 1
        mode = state.get("sort", "natural")
        if mode == "extension":
            aa, bb = (
                Path(a["name"]).suffix.casefold(),
                Path(b["name"]).suffix.casefold(),
            )
            if aa != bb:
                return (aa > bb) - (aa < bb)
        if mode in ("size", "mtime") and a[mode] != b[mode]:
            return -1 if a[mode] > b[mode] else 1
        aa, bb = os.fsencode(a["name"]), os.fsencode(b["name"])
        return compare(aa, len(aa), bb, len(bb)) or ((aa > bb) - (aa < bb))

    ordered = sorted(result, key=cmp_to_key(order))
    if state.get("reverse"):
        return [x for x in reversed(ordered) if x["directory"]] + [
            x for x in reversed(ordered) if not x["directory"]
        ]
    return ordered


def preview(entry, limit=32768):
    path = Path(entry["path"])
    if entry["directory"]:
        with os.scandir(path) as listing:
            from itertools import islice

            return "\n".join(
                e.name + ("/" if e.is_dir() else "") for e in islice(listing, 60)
            )
    if not path.is_file():
        return "Special file"
    with path.open("rb") as stream:
        data = stream.read(limit)
    if b"\0" in data:
        return "Binary file"
    return data.decode("utf-8", errors="replace")


def display(value):
    return "".join(c if c.isprintable() else f"\\u{ord(c):04x}" for c in value)
