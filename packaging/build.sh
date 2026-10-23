#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"
cargo build --release --locked --offline
read -r release_version release_codename < <(python3 -c 'import runpy; m=runpy.run_path("python/cosmos_tui/core/metadata.py"); print(m["VERSION"], m["CODENAME"].lower())')
bundle_name="cosmos-$release_version-$release_codename-linux-x86_64"
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    echo 'This initial package recipe targets Linux x86_64 only.' >&2
    exit 1
fi
mkdir -p "dist/$bundle_name/bin" "dist/$bundle_name/config"
cp target/release/cosmos "dist/$bundle_name/bin/"
cp config/config.toml config/cosmosrc config/terminal-agent-prompt.md "dist/$bundle_name/config/"
cp README.md RELEASE.md "dist/$bundle_name/"
cp cosmos "dist/$bundle_name/"
mkdir -p "dist/$bundle_name/design"
cp design/实施方案-v0.1.md design/实施进度.md design/实施设计与决策记录.md design/架构边界修订.md design/Python-Textual迁移.md design/UI分区与Agent接入.md "dist/$bundle_name/design/"
mkdir -p "dist/$bundle_name/docs" "dist/$bundle_name/examples" "dist/$bundle_name/sdk/python"
cp docs/framework.md docs/workspace.md docs/viewer.md docs/ui-api.md docs/shell.md docs/architecture.md docs/cli.md docs/input-method.md docs/status-bar.md docs/themes.md docs/mouse.md docs/settings.md docs/notifications.md "dist/$bundle_name/docs/"
cp examples/demo.py examples/demo.mod.toml examples/surface.py examples/surface.mod.toml examples/ui-demo.py examples/ui-demo.mod.toml "dist/$bundle_name/examples/"
cp sdk/python/cosmos_mod.py "dist/$bundle_name/sdk/python/"
mkdir -p "dist/$bundle_name/python/cosmos_tui" "dist/$bundle_name/dev"
cp python/README.md "dist/$bundle_name/python/"
python3 - "dist/$bundle_name/python/cosmos_tui" <<'PY'
from pathlib import Path
import shutil
import sys
destination = Path(sys.argv[1])
if destination.exists():
    shutil.rmtree(destination)
shutil.copytree('python/cosmos_tui', destination,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
PY
cp python/README.md python/requirements*.txt "dist/$bundle_name/python/"
cp dev/cosmos-textual "dist/$bundle_name/dev/"
mkdir -p "dist/$bundle_name/shell" "dist/$bundle_name/terminal_agent/terminal_agent" "dist/$bundle_name/terminal_agent/shell" "dist/$bundle_name/terminal_agent/native"
mkdir -p "dist/$bundle_name/shell/completions"
cp shell/completions/cosmos.bash "dist/$bundle_name/shell/completions/"
cp shell/cosmos.bash "dist/$bundle_name/shell/"
cp terminal_agent/terminal_agent/*.py "dist/$bundle_name/terminal_agent/terminal_agent/"
cp terminal_agent/shell/agent.bash "dist/$bundle_name/terminal_agent/shell/"
cp terminal_agent/native/readline.c "dist/$bundle_name/terminal_agent/native/"

python3 packaging/licenses.py "dist/$bundle_name/licenses"
printf '%s\n' 'PDF viewing requires pdfinfo, pdftoppm, pdftotext (Poppler / poppler-utils) on PATH; not bundled.' > "dist/$bundle_name/pdf-dependencies.txt"
ldd target/release/cosmos > "dist/$bundle_name/runtime-dependencies.txt"
(cd "dist/$bundle_name" && find bin config licenses docs examples sdk design python dev shell terminal_agent -type f -exec sha256sum {} + > SHA256SUMS && sha256sum cosmos README.md RELEASE.md runtime-dependencies.txt pdf-dependencies.txt >> SHA256SUMS)
tar -C dist -czf "dist/$bundle_name.tar.gz" "$bundle_name"
sha256sum "dist/$bundle_name.tar.gz" > "dist/$bundle_name.tar.gz.sha256"
printf '%s\n' "$project_root/dist/$bundle_name.tar.gz"
