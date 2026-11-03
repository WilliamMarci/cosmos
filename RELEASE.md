# Cosmos Arche · 0.2.2

- Channel: development / prerelease
- Date: 2026-11-03
- Author: William Marci

## Changes

- The install menu can edit the software installation directory (`p`) and command directory (`b`), including paths containing spaces. `--prefix` and `--bin-dir` remain available for scripted installations.
- Installation now reports download, verification, copying, extraction and environment setup progress over SSH and in redirected logs.
- Outside Cosmos, `cosmos open FILE` launches Reader directly without creating a workspace, coordinator or shell. Inside a Cosmos backend pane it retains the integrated Reader. Standalone Reader supports navigation, search, mouse input and resizing; `q` exits.
- `cosmos update` retrieves releases from GitHub, preserves feature selection and reuses optional components only when their contents and permissions match the target release fingerprint. Updates install in a new version directory and switch the command entry after validation; failures preserve the old entry and installation.
- Developer release automation reuses cached PDF/Rime payloads. On cache miss, matching published native components and their corresponding sources can be restored after recipe and SHA256 verification. Developer build scripts are excluded from installed packages.

## Downloads and installation

Linux x86_64 / x86-64-v2 has two compatibility tiers: glibc ≥ 2.28 built on AlmaLinux 8, and glibc ≥ 2.34 built on AlmaLinux 9. Download this release's `install.sh` and run `bash install.sh`; it selects the highest compatible core, then opens the small multi-select installer. PDF, Rime + 雾凇 and Agent are separate optional downloads. Rime defaults to `rime_ice`.

Core includes CPython 3.12, pinned Python wheel dependencies, Tmux, coordinator and native adapters. End users need no compiler, CMake, venv setup or sudo. Software and private libraries stay in the selected installation directory; configuration, cache and mutable state use XDG user directories. Shell startup files and global packages are untouched. `components.json` records compatibility, archive hashes, payload fingerprints and sizes; third-party notices and corresponding optional-component sources accompany the binaries.

Users upgrading from 0.2.1 need to run the 0.2.2 installer once to obtain the new `cosmos update` command. Detach clients and stop the previous coordinator before reopening the new version. Existing Tmux applications and older installation directories are preserved.

The JSON-RPC protocol remains major 1, minor 4; the configuration format remains version 1. This development release does not claim completion of the full planned feature set or frozen external Mod APIs. OCR, SVG/EPS/ICO extensions and PDF text selection remain outside the current scope.
