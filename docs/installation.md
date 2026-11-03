# User installation

Download the `core` Linux x86_64 / glibc 2.28 or 2.34 archive from the [GitHub release](https://github.com/WilliamMarci/cosmos/releases). Extract it and run `./install.sh`. Do not use sudo. The GitHub-generated source archives are for development and are not installable binary packages.

The installer checks Linux/CPU architecture, glibc, required x86-64-v2 CPU flags, writable directories, free space and archive checksums before installing. The glibc 2.28 tier is built on AlmaLinux 8; the glibc 2.34 tier is built on AlmaLinux 9. These target AlmaLinux/Rocky/RHEL 8 and newer compatible glibc distributions. The single-file release `install.sh` bootstrap uses the published TSV form of the same manifest to select the highest compatible core tier without a JSON parser; core archives can also be downloaded manually. ARM64 and musl/Alpine have no matching package yet and are rejected. Being an SSH server does not change these requirements.

The line-based Bash TUI supports multi-selection with numeric toggles and Enter; it needs no dialog/fzf/ncurses UI dependency. Core is required; Agent, Bash command assistant, PDF and Rime are selectable. Only selected Agent/PDF/Rime archives are downloaded, checked against `components.json` (version, compatibility, URL, SHA256, compressed and unpacked size), then extracted. There is no end-user compilation, package-manager use or system package installation.

```bash
./install.sh
./install.sh --yes --features core,assistant,pdf,rime \
  --prefix "$HOME/apps/cosmos-0.2.1" --bin-dir "$HOME/.local/bin"
./install.sh --check --features core
```

Defaults:

- Software: `${XDG_DATA_HOME:-~/.local/share}/cosmos/0.2.1`.
- Command: `~/.local/bin/cosmos` symlink; `--bin-dir` overrides it. Existing unmanaged commands are never overwritten.
- Configuration: `${XDG_CONFIG_HOME:-~/.config}/cosmos`.
- Cache: `${XDG_CACHE_HOME:-~/.cache}/cosmos` (including Python bytecode).
- Logs/Rime mutable state: `${XDG_STATE_HOME:-~/.local/state}/cosmos`.
- Native optional components: installation `vendor/pdf` and `vendor/rime`, with `rime_ice` selected by default. Explicit `COSMOS_RIME_*` overrides remain supported.

Core includes a relocatable CPython 3.12 runtime, pinned Python wheel dependencies, Tmux, coordinator and precompiled file/Bash integrations. Rust, uv, CMake, compilers and Bun/npm are build dependencies only. Agent is compiled for the baseline CPU tier, without requiring AVX2. PDF includes private Poppler utilities; Rime includes private librime/Lua and compiled 雾凇 data. Third-party licenses and corresponding optional-component sources are published alongside the binaries; Cosmos's own code is MIT.

For offline installation, place the selected component archives and published `components.json` beside the extracted `install.sh`; downloads are then unnecessary. The installer never edits PATH, shell rc files, desktop Rime settings or global environments. If `~/.local/bin` is not on PATH, it prints the full command path.

Install upgrades to a new versioned directory. Older installations/configuration are preserved. Detach clients and run the previous `cosmos stop` before reopening the new version; terminal applications remain running. Removing an installation directory and its command symlink removes the application; user configuration/cache/state are intentionally retained.

# Building releases

`packaging/build.sh core|agent|pdf|rime` runs in the matching AlmaLinux 8/9 container used by `.github/workflows/release.yml`. Build tools and development libraries are installed only in this ephemeral builder. Native binaries are checked with `readelf` against their glibc 2.28/2.34 tier. The build collects third-party notices and sources, generates checksums, tests an unprivileged clean installation, and publishes separate GitHub Release assets plus a compatibility manifest. Source trees, node_modules, Python environments and generated binaries are excluded from Git.
