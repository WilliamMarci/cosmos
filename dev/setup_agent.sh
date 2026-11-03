#!/usr/bin/env bash
set -euo pipefail
cosmos_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if ! command -v bun >/dev/null; then
    npm install --prefix "$cosmos_root/.build/agent-runtime" --no-audit --no-fund bun@1.4.2
    cosmos_bun="$cosmos_root/.build/agent-runtime/node_modules/.bin/bun"
else
    cosmos_bun=$(command -v bun)
fi
export PATH="$(dirname -- "$cosmos_bun"):$PATH"
cd "$cosmos_root/vendor/opencode"
"$cosmos_bun" install --frozen-lockfile --ignore-scripts
"$cosmos_bun" run --cwd packages/core fix-node-pty
"${COSMOS_BUILD_PYTHON:-$cosmos_root/.venv/bin/python}" "$cosmos_root/dev/prepare_agent.py"
