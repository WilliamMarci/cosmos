"""Post-TUI summary, written only after the terminal driver has restored stdout."""

import subprocess
import sys

from rich.text import Text

from cosmos_tui.core.paths import ASSET_DIR
from cosmos_tui.core.hints import command


def show_farewell(result, backend, stream=None):
    stream = stream or sys.stdout
    target = getattr(backend, "session_id", None) or backend.session
    try:
        retained = (
            subprocess.run(
                [*backend.argv, "has-session", "-t", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        retained = None
    reason = (result or {}).get("reason", "exit")
    logo = (ASSET_DIR / "cosmos-logo.ansi").read_text()
    if not stream.isatty():
        logo = Text.from_ansi(logo).plain
    stream.write("\n" + logo.rstrip() + "\n\n")
    stream.write(f"{reason} · {backend.session}\n")
    if retained:
        stream.write("Session retained · applications continue running\n")
        stream.write(f"Reconnect: {command(backend.session)}\n")
    elif retained is False:
        stream.write("Session ended · no session to reconnect\n")
    else:
        stream.write("Session state unavailable\n")
    stream.flush()
