# Cosmos file management

`open DIRECTORY` in a Cosmos Bash pane and `cosmos open DIRECTORY` route to a Cosmos-owned full-pane file view. No system or vendored Yazi executable is launched. The underlying shell continues running; q/Escape restores it. The directory must belong to the running host; no SSH filesystem integration is provided.

## Current implementation

The source-extracted Yazi `yazi-shared/src/natsort.rs` is compiled through `native/files/lib.rs` into `.build/libcosmos_files.so`. Run `bash dev/build_files.sh` after cloning the Cosmos source. Upstream commit, original attribution and MIT license are retained in native/files/ORIGIN.md and LICENSE-Yazi. This std-only extraction builds with the existing Rust toolchain; it does not require building the upstream Yazi workspace.

`features/files/model.py` owns directory snapshots and invokes that native comparator, with directories first. Natural, size and modification-time order are supported. Hidden files are initially omitted; the name filter is literal, case-insensitive unless it contains an uppercase character. Scans are bounded to 50000 entries and previews to 32 KiB/60 lines. Special files are not read as regular files.

`features/files/view.py` owns the full-pane layout: directory header, file list, optional right preview at sufficient width, compact footer. Its RGB/background and cell content use the existing Cosmos renderer, palette and event path. There is no second terminal output owner. The global status mode is FILES.

Keys are registered under `files.*` in shared Keybindings, help and Ctrl+P Actions: arrows/hjkl navigate, Enter opens, Home/End and PageUp/PageDown move through entries, . toggles hidden entries, s cycles sort, / opens the pane-local bottom filter, ? shows help. Mouse clicks select rows and the wheel moves selection.

Supported files open through the existing Reader; closing it returns to the originating file list. Other regular files use the existing external application route. Errors become notifications instead of terminating the UI. File browsing never changes the shell's current directory.

## State and implementation boundary

The internal pane presentation metadata uses `kind = "files"`, `path`, `cursor`, and optional `filter`, `show_hidden`, `sort`. It is retained in the existing Tmux pane metadata, not a Yazi child process. Native sorting and listing are separate from presentation so the future sidebar can reuse them.

This stage is directory navigation/opening, not Yazi feature parity. Copy/move/rename/delete, multi-selection, tasks/progress, archive/plugin/VFS capabilities, settings defaults and the collapsible left dock are not delivered yet. The right-hand preview currently handles bounded text and directory names; rich previews remain to be integrated with the shared Reader. No plugin or file-operation API is declared public by this stage.
