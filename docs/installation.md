# User installation

Download the `core` Linux x86_64 / glibc 2.28 or 2.34 archive from the [GitHub release](https://github.com/WilliamMarci/cosmos/releases). Extract it and run `./install.sh`. Do not use sudo. The GitHub-generated source archives are for development and are not installable binary packages.

The installer checks Linux/CPU architecture, glibc, required x86-64-v2 CPU flags, writable directories, free space and archive checksums before installing. The glibc 2.28 tier is built on AlmaLinux 8; the glibc 2.34 tier is built on AlmaLinux 9. These target AlmaLinux/Rocky/RHEL 8 and newer compatible glibc distributions. The single-file release `install.sh` bootstrap uses the published TSV form of the same manifest to select the highest compatible core tier without a JSON parser; core archives can also be downloaded manually. ARM64 and musl/Alpine have no matching package yet and are rejected. Being an SSH server does not change these requirements.

The line-based Bash TUI supports multi-selection with numeric toggles, `p` to edit the software installation directory, `b` to edit the command directory, and Enter to continue; it needs no dialog/fzf/ncurses UI dependency. Core is required; Agent, Bash command assistant, PDF and Rime are selectable. Only selected Agent/PDF/Rime archives are downloaded, checked against `components.json` (version, compatibility, URL, SHA256, compressed and unpacked size), then extracted. There is no end-user compilation, package-manager use or system package installation.

```bash
./install.sh
./install.sh --yes --features core,assistant,pdf,rime \
  --prefix "$HOME/apps/cosmos-0.2.4" --bin-dir "$HOME/.local/bin"
./install.sh --check --features core
```

Defaults:

- Software: `${XDG_DATA_HOME:-~/.local/share}/cosmos/0.2.4`.
- Command: `~/.local/bin/cosmos` symlink; `--bin-dir` overrides it. Existing unmanaged commands are never overwritten.
- Configuration: `${XDG_CONFIG_HOME:-~/.config}/cosmos`.
- Cache: `${XDG_CACHE_HOME:-~/.cache}/cosmos` (including Python bytecode).
- Logs/Rime mutable state: `${XDG_STATE_HOME:-~/.local/state}/cosmos`.
- Native optional components: installation `vendor/pdf` and `vendor/rime`, with `rime_ice` selected by default. Explicit `COSMOS_RIME_*` overrides remain supported.

Core includes a relocatable CPython 3.12 runtime, pinned Python wheel dependencies, Tmux, coordinator and precompiled file/Bash integrations. Installation moves the offline wheels into the private `.venv` site-packages and removes the staging `python-deps` directory. Application modules are registered with a private `.pth` file; installed helpers and Agent/MCP subprocesses use this venv with `-I`, independently of host Python/Conda settings. The installer validates imports with a fresh isolated interpreter. Rust, uv, CMake, compilers and Bun/npm are build dependencies only. Agent is compiled for the baseline CPU tier, without requiring AVX2. PDF includes private Poppler utilities; Rime includes private librime/Lua and compiled 雾凇 data. Third-party licenses and corresponding optional-component sources are published alongside the binaries; Cosmos's own code is MIT.

## Offline installation

On a connected machine, download assets from the **same release**: the core archive for a compatible glibc tier, `components.json`, and the selected Agent/PDF/Rime archives. Copy them to the server. For AlmaLinux 8 use the 2.28 tier; AlmaLinux 9 can use either tier. Extract the core archive and run its installer:

```bash
./install.sh --offline --package-dir /path/to/downloaded-assets
```

`--offline` forbids network access. A compatible archive already present in `--package-dir` is preferred, including a lower glibc tier when the highest compatible tier is absent. Missing selected archives produce a clear error. Hash/CPU/glibc checks still apply. Select only the components downloaded; core-only installation needs no optional archive.

Alternatively, the single-file release `install.sh` can bootstrap offline if that directory also contains `components.tsv`, `components.json` and the compatible core archive:

```bash
bash install.sh --offline --package-dir /path/to/downloaded-assets
```

Online requests announce their target **before connecting**, show bounded retry attempts and timeouts, and report offline instructions on failure. No installer can bypass a server's GitHub network restrictions.

 The installer never edits PATH, shell rc files, desktop Rime settings or global environments. If `~/.local/bin` is not on PATH, it prints the full command path.

Install upgrades to a new versioned directory. Older installations/configuration are preserved. Detach clients and run the previous `cosmos stop` before reopening the new version; terminal applications remain running. To end all verified Cosmos backend sessions and pending work, use `cosmos stop --all`: it previews the affected sessions/tasks and asks for confirmation. Plain `cosmos stop` retains terminal applications. Bundled backends are named `cosmos-tmux`, use the default independent socket `cosmos`, and have private ownership records checked against the process UID, executable and start time before shutdown. `COSMOS_TMUX` remains an executable override; source checkouts can use system `tmux`. Already running old backends keep their old process title until explicitly stopped and restarted.

Run `INSTALL_DIR/uninstall.sh` to remove that installation. It previews affected backend sessions and processes using that installation, asks for confirmation, checks for residual processes, and removes only its own command symlink and software tree. User configuration/cache/state are retained. `--yes` confirms non-interactively.

Agent child processes preserve external HTTP proxies while adding localhost/loopback to `NO_PROXY` and `no_proxy`, so their private local server is reachable. Failed Agent panes retain error output and exit status instead of immediately disappearing. The Bash assistant prints its actual import exception when dependencies cannot load.

## Terminal and host environment

Core packages include a private terminfo database and inspector. Unsupported terminal names fall back to `xterm-256color` when available; the original terminal name remains available for graphics detection. Known truecolor terminal names and SSH's common `xterm-256color` default to truecolor; explicit `TEXTUAL_COLOR_SYSTEM=256` is respected for limited terminals.

Native Cosmos libraries use private ELF search paths. The launcher isolates its own runtime from host `LD_LIBRARY_PATH`/`LD_PRELOAD` and Python overrides, while internal Bash restores the original host environment before user initialization and removes duplicate path entries. System applications are not given Cosmos's private library directory. Flatpak is not a Cosmos dependency.


# Building releases

`packaging/build.sh core|agent|pdf|rime` runs in the matching AlmaLinux 8/9 container used by `.github/workflows/release.yml`. Build tools and development libraries are installed only in this ephemeral builder. Native binaries are checked with `readelf` against their glibc 2.28/2.34 tier. The build collects third-party notices and sources, generates checksums, tests an unprivileged clean installation, and publishes separate GitHub Release assets plus a compatibility manifest. Source trees, node_modules, Python environments and generated binaries are excluded from Git.

Developers can dispatch the complete build with `dev/release.sh build --ref main`, follow it with `dev/release.sh watch RUN_ID`, and publish the resulting draft after server acceptance with `dev/release.sh publish vVERSION`. This wrapper requires authenticated GitHub CLI only on the developer's machine and is excluded from installed packages. `build --core-only` builds just the two core compatibility tiers for targeted fixes and does not create a release.

PDF/Rime build outputs and their corresponding sources are cached separately for each component and glibc tier. The cache key depends on the native component recipe and packaging code, rather than ordinary application changes or the release version. A cache hit only repackages the existing payload for the current version; a missing or changed key rebuilds it. `--rebuild-optional` bypasses caches for that run. GitHub may evict caches; eviction causes a rebuild, never omission of a required component. The workflow still verifies archive hashes and core installation before creating a draft.


The installer reports byte counts/percentages for downloads, integrity checks, core copying and component extraction, followed by environment/entry setup. Feedback uses plain lines, including redirected logs and SSH sessions.

`cosmos update` discovers the newest published numeric version on GitHub (including the development/prerelease channel), retains the installed feature selection and command directory, installs to a new sibling version directory, and switches the command symlink only after successful validation. An optional component is copied from the existing installation only when its file contents and permissions match the new release's payload fingerprint; modified or incompatible components are downloaded and SHA256-checked instead. Older manifests without payload fingerprints safely fall back to downloads. The old installation and running sessions remain available; stop the previous coordinator before reopening the updated application. Source checkouts should be updated with Git.

On a build-cache miss, the developer workflow can restore PDF/Rime from a published release only when both the native build recipe and ABI/packaging collector match byte for byte; binary and corresponding-source hashes are checked before reuse. `--rebuild-optional` bypasses this fallback as well as caches.
