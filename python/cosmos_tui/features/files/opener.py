"""Route a directory to a Cosmos-owned file view in the source backend pane."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            error.stderr.strip() or "Cannot open directory in Cosmos"
        ) from error


def open_directory(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Not a directory")
    pane = os.getenv("TMUX_PANE", "")
    if not re.fullmatch(r"%\d+", pane) or not os.getenv("TMUX"):
        raise RuntimeError("Open directories from a Cosmos shell")
    # Use the configured Cosmos backend socket, never an unrelated Tmux server.
    from cosmos_tui.terminal.backend import command

    argv = command()
    socket = _run([*argv, "display-message", "-p", "#{socket_path}"]).stdout.strip()
    if os.path.realpath(os.environ["TMUX"].split(",")[0]) != os.path.realpath(socket):
        raise RuntimeError("Directory opening requires a Cosmos backend pane")
    wire = base64.b64encode(
        json.dumps(dict(kind="files", path=str(path), cursor=0)).encode()
    ).decode()
    _run([*argv, "set-option", "-p", "-t", pane, "@cosmos_viewer", wire])
