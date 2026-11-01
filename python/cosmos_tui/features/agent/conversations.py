"""Export an Agent conversation through OpenCode's supported CLI contract."""

import json
import os
from pathlib import Path
import re
import subprocess

from cosmos_tui.features.agent.profile import (
    initialize_profile,
    profile_root,
    write_private_json,
)


def export_conversation(session, output=None):
    if not re.fullmatch(r"ses_[A-Za-z0-9_-]+", session):
        raise ValueError("expected an Agent conversation ID beginning ses_")
    from cosmos_tui.features.agent.launch import environment, runtime, native_runtime

    command, cwd = runtime()
    if not native_runtime(command, cwd):
        raise RuntimeError(
            "Cosmos Agent is not installed; use OpenCode's own session export"
        )
    os.umask(0o077)
    root = initialize_profile()
    (root / "tmp").mkdir(exist_ok=True, mode=0o700)
    env = environment(os.getenv("COSMOS_TMUX_SOCKET", "cosmos"), "")
    try:
        result = subprocess.run(
            command + ["session", "export", session, "--standalone", "--sanitize"],
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Agent conversation export timed out") from error
    if result.returncode:
        raise RuntimeError(
            "Agent conversation export failed; check the private Agent log"
        )
    return write_private_json(
        Path(output).expanduser()
        if output
        else profile_root() / "exports" / (session + ".json"),
        json.loads(result.stdout),
    )
