"""Session management and retained terminal history without attaching a UI."""

import json
from pathlib import Path

from cosmos_tui.terminal.tmux import Tmux


async def listing():
    backend = Tmux()
    try:
        output = await backend.cli(
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_windows}\t#{session_created}\t#{session_id}",
        )
    except RuntimeError as error:
        if "no server running" in str(error) or "No such file or directory" in str(
            error
        ):
            return []
        raise
    return [
        dict(name=name, windows=int(windows), created=int(created), id=ident)
        for name, windows, created, ident in (
            row.split("\t") for row in output.splitlines()
        )
    ]


async def create(name, cwd=None):
    Tmux.validate_name(name)
    backend = Tmux(name)
    arguments = [
        "-f",
        "/dev/null",
        "new-session",
        "-d",
        "-P",
        "-F",
        "#{session_id}",
        "-s",
        name,
    ]
    if cwd:
        directory = Path(cwd).expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise ValueError(f"not a directory: {directory}")
        arguments += ["-c", str(directory)]
    session_id = (await backend.cli(*arguments, backend.shell_command())).strip()
    await backend.cli(
        "set-option", "-t", session_id, "default-command", backend.shell_command()
    )
    return session_id


async def exists(name):
    return await Tmux(name).resolve_session_id() is not None


async def kill(name):
    backend = Tmux(name)
    session_id = await backend.resolve_session_id()
    if session_id is None:
        raise ValueError(f"session not found: {name}")
    await backend.cli("kill-session", "-t", session_id)


async def rename(name, new_name):
    Tmux.validate_name(new_name)
    backend = Tmux(name)
    session_id = await backend.resolve_session_id()
    if session_id is None:
        raise ValueError(f"session not found: {name}")
    await backend.cli("rename-session", "-t", session_id, new_name)


async def history(name, pane=None, lines=None, ansi=False):
    backend = Tmux(name)
    # Resolve the exact session ID, then enumerate stable pane IDs; --pane cannot
    # accidentally export a pane belonging to another session.
    session_id = await backend.resolve_session_id()
    if session_id is None:
        raise ValueError(f"session not found: {name}")
    output = await backend.cli(
        "list-panes",
        "-s",
        "-t",
        session_id,
        "-F",
        "#{pane_id}\t#{window_index}\t#{pane_index}",
    )
    panes = [row.split("\t") for row in output.splitlines()]
    if pane:
        panes = [row for row in panes if row[0] == pane]
        if not panes:
            raise ValueError(f"pane {pane} does not belong to session {name}")
    result = []
    for pane_id, window, index in panes:
        arguments = ["capture-pane", "-p", "-t", pane_id, "-S", "-", "-E", "-"]
        if ansi:
            arguments += ["-e"]
        text = await backend.cli(*arguments)
        if lines is not None:
            text = "".join(text.splitlines(keepends=True)[-lines:])
        result.append(
            dict(
                session=name,
                session_id=session_id,
                window=int(window),
                pane_index=int(index),
                pane=pane_id,
                text=text,
            )
        )
    return result


def format_history(rows, structured=False):
    if structured:
        return json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    if len(rows) == 1:
        return rows[0]["text"]
    return "".join(
        f"=== {row['session']}:{row['window']}.{row['pane_index']} ({row['pane']}) ===\n{row['text']}"
        for row in rows
    )
