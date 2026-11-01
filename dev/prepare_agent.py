"""Apply the tracked, opt-in Cosmos branding patch to the pinned OpenCode tree."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from cosmos_tui.ui.logo import logo_lines  # noqa: E402


def prepare():
    vendor = ROOT / "vendor/opencode"
    for patch in sorted((ROOT / "integrations/opencode").glob("*.patch")):
        check = subprocess.run(
            ["git", "apply", "--check", str(patch)], cwd=vendor, capture_output=True
        )
        if check.returncode == 0:
            subprocess.run(["git", "apply", str(patch)], cwd=vendor, check=True)
        else:
            subprocess.run(
                ["git", "apply", "--reverse", "--check", str(patch)],
                cwd=vendor,
                check=True,
            )
    (vendor / "packages/core/src/tool/cosmos-permissions.ts").write_text(
        (ROOT / "integrations/opencode/cosmos-permissions.ts").read_text()
    )
    (vendor / "packages/core/src/tool/cosmos-interface.ts").write_text(
        (ROOT / "integrations/opencode/cosmos-interface.ts").read_text()
    )
    task_runtime = vendor / "packages/core/src/cosmos"
    task_runtime.mkdir(exist_ok=True)
    for source in (ROOT / "integrations/opencode/tasks").glob("*.ts"):
        if not source.name.endswith(".test.ts"):
            (task_runtime / source.name).write_text(source.read_text())
    (vendor / "packages/tui/src/theme/assets/cosmos.json").write_text(
        (ROOT / "python/cosmos_tui/assets/agent-cosmos.json").read_text()
    )
    component = vendor / "packages/tui/src/component"
    (component / "dialog-cosmos-permissions.tsx").write_text(
        (ROOT / "integrations/opencode/dialog-cosmos-permissions.tsx").read_text()
    )
    (component / "cosmos-logo.tsx").write_text(
        (ROOT / "integrations/opencode/cosmos-logo.tsx").read_text()
    )
    (component / "cosmos-logo-data.ts").write_text(
        "export const cosmosLines = "
        + json.dumps(logo_lines(), ensure_ascii=False)
        + "\n"
    )


if __name__ == "__main__":
    prepare()
