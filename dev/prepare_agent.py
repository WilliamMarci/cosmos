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
    component = vendor / "packages/tui/src/component"
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
