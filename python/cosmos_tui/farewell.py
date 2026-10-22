"""Post-TUI summary, written only after the terminal driver has restored stdout."""

from pathlib import Path
import shlex
import subprocess
import sys

from rich.text import Text


def show_farewell(result, backend, stream=None):
    stream = stream or sys.stdout
    try:
        retained = (
            subprocess.run(
                [*backend.argv, "has-session", "-t", backend.session],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        retained = None
    reason = (result or {}).get("reason", "exit")
    logo = (Path(__file__).parent / "assets/cosmos-logo.ansi").read_text()
    if not stream.isatty():
        logo = Text.from_ansi(logo).plain
    stream.write("\n" + logo.rstrip() + "\n\n")
    stream.write(f"{reason} · {backend.session}\n")
    if retained:
        stream.write("Session retained · applications continue running\n")
        entry = Path(__file__).resolve().parents[2] / "cosmos"
        stream.write(f"Reconnect: {shlex.join([str(entry), backend.session])}\n")
    elif retained is False:
        stream.write("Session ended · no session to reconnect\n")
    else:
        stream.write("Session state unavailable\n")
    stream.flush()
