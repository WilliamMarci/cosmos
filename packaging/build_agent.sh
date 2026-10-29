#!/usr/bin/env bash
# Build the patched OpenCode CLI only; invoked by the Cosmos release recipe.
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $# != 1 ]]; then
    echo 'Usage: packaging/build_agent.sh BUNDLE_DIRECTORY' >&2
    exit 2
fi
bundle_root=$(realpath -m -- "$1")
bash "$project_root/dev/setup_agent.sh"
cosmos_bun=$(command -v bun || true)
cosmos_bun=${cosmos_bun:-"$project_root/.build/agent-runtime/node_modules/.bin/bun"}
export PATH="$(dirname -- "$cosmos_bun"):$PATH"
cd "$project_root/vendor/opencode"
OPENCODE_CHANNEL=cosmos "$cosmos_bun" run packages/cli/script/build.ts \
    --target=opencode-linux-x64 --skip-install --skip-web-ui --outdir="$project_root/.build/opencode-bundle"
install -Dm755 "$project_root/.build/opencode-bundle/cli-linux-x64/bin/opencode" "$bundle_root/bin/cosmos-agent"
install -Dm644 "$project_root/integrations/opencode/LICENSE-OpenCode" "$bundle_root/licenses/opencode/LICENSE"
cp "$project_root/integrations/opencode/README.md" "$bundle_root/licenses/opencode/ORIGIN.md"
