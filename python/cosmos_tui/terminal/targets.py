"""Stable Tmux targets and switch operations; display indices are never identities."""

import re


def target(kind, value):
    prefix = {"session": r"\$", "window": "@", "pane": "%"}[kind]
    if not re.fullmatch(prefix + r"\d+", value):
        raise ValueError("Invalid " + kind + " ID")
    return value


async def select(backend, row):
    if row["kind"] == "pane":
        pane = target("pane", row["pane_id"])
        actual = await backend.request(f"display-message -p -t {pane} '#{{window_id}}'")
        if actual != [row["window_id"]]:
            raise RuntimeError("Pane moved or closed; refresh Switch")
    await backend.select_window(row)
    if row["kind"] == "pane":
        await backend.request("select-pane -t " + row["pane_id"])


async def rename(backend, row, name):
    name = name.strip()
    if not name or len(name) > 80 or any(not c.isprintable() for c in name):
        raise ValueError("Enter a printable name (1–80 characters)")
    kind = row["kind"]
    ident = target(kind, row[kind + "_id"])
    if kind == "session":
        backend.validate_name(name)
        command = f"rename-session -t {ident} " + backend.quote(name)
    elif kind == "window":
        command = f"rename-window -t {ident} " + backend.quote(name)
    else:
        command = f"set-option -p -t {ident} @cosmos_name " + backend.quote(name)
    await backend.request(command)
    if kind == "session" and ident == backend.session_id:
        backend.session = name


async def new_window(backend, row):
    sid = target("session", row["session_id"])
    return await backend.request(f'new-window -t {sid}: -c "#{{pane_current_path}}"')


async def split(backend, row, horizontal):
    pane = row.get("pane_id")
    ident = target("pane", pane) if pane else target("window", row["window_id"])
    await backend.request(
        f"split-window -t {ident} "
        + ("-h" if horizontal else "-v")
        + ' -c "#{pane_current_path}"'
    )
