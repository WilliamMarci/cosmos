"""Post-TUI summary, written only after the terminal driver has restored stdout."""

import subprocess
import sys

from rich.text import Text

from cosmos_tui.core.hints import command
from cosmos_tui.ui.logo import DEFAULT_LOGO, render_logo


def show_farewell(result, backend, stream=None, logo_style=None):
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
    logo = render_logo(logo_style or DEFAULT_LOGO)
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
