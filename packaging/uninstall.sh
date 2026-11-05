#!/usr/bin/env bash
set -euo pipefail
cosmos_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec "$cosmos_root/cosmos" _uninstall "$@"
