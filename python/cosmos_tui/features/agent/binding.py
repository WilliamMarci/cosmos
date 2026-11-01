"""A tool connection belongs to one workspace incarnation, not just a name."""

from dataclasses import dataclass
import hashlib
import json
import os
import subprocess
from pathlib import Path


@dataclass
class WorkspaceBinding:
    name: str
    identity: tuple | None = None

    def __post_init__(self):
        raw = os.getenv("COSMOS_WORKSPACE_BINDING")
        if raw:
            record = json.loads(raw)
            if record.get("name") == self.name:
                self.identity = tuple(record["identity"])

    @staticmethod
    def process_identity(pid):
        try:
            start = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
        except (OSError, IndexError):
            start = None
        return str(pid), start

    def validate(self, rows):
        identities = {str(row["pid"]) for row in rows}
        if len(identities) != 1:
            raise ValueError("Cosmos workspace is unavailable; reconnect explicitly")
        pid = identities.pop()
        current = self.process_identity(pid)
        if self.identity is None:
            self.identity = current
        elif self.identity != current:
            raise ValueError(
                "Cosmos workspace service changed; reconnect explicitly before accessing targets"
            )
        return (
            "workspace_"
            + hashlib.sha256(repr((self.name, current)).encode()).hexdigest()[:24]
        )


def launch_binding(name):
    """Capture the existing workspace before starting the native Agent process."""
    from cosmos_tui.terminal.tmux import Tmux

    result = subprocess.run(
        Tmux().argv[:1] + ["-L", name, "display-message", "-p", "#{pid}"],
        capture_output=True,
        text=True,
        timeout=3,
    )
    pid = result.stdout.strip()
    if result.returncode or not pid.isdigit():
        return None
    return json.dumps(dict(name=name, identity=WorkspaceBinding.process_identity(pid)))
