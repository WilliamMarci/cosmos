"""User-facing command hints use the installed public entry point."""

import shlex


def command(*arguments):
    """Format a copyable command independently of the installation directory."""
    return shlex.join(["cosmos", *map(str, arguments)])


def unavailable(component):
    return f"{component} is unavailable; run {command('doctor')} for diagnostics"


def restart_commands(session, debug=False):
    return command("stop") + "\n  " + command(session, *(["--debug"] if debug else []))
