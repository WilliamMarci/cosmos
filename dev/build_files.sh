#!/usr/bin/env bash
set -euo pipefail
cosmos_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$cosmos_root/.build"
rustc --edition=2024 --crate-type=cdylib "$cosmos_root/native/files/lib.rs" -o "$cosmos_root/.build/libcosmos_files.so"
