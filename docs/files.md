# Cosmos file management

`open DIRECTORY` in a Cosmos Bash pane and `cosmos open DIRECTORY` route to a Cosmos-owned full-pane file view. No system or vendored Yazi executable is launched. The underlying shell continues running; q/Escape restores it. The directory must belong to the running host; no SSH filesystem integration is provided.

## Current implementation

The source-extracted Yazi `yazi-shared/src/natsort.rs` is compiled through `native/files/lib.rs` into `.build/libcosmos_files.so`. Run `bash dev/build_files.sh` after cloning the Cosmos source. Upstream commit, original attribution and MIT license are retained in native/files/ORIGIN.md and LICENSE-Yazi. This std-only extraction builds with the existing Rust toolchain; it does not require building the upstream Yazi workspace.

`features/files/model.py` owns directory snapshots and invokes that native comparator, with directories first. Natural, size, modification-time and extension order are supported, with reversible direction and directories first. Hidden files are initially omitted; the name filter is literal, case-insensitive unless it contains an uppercase character. Scans are bounded to 50000 entries and previews to 32 KiB/60 lines. Special files are not read as regular files.

`features/files/view.py` owns navigation and state; `render.py` owns the Yazi-like parent/current/preview columns (three columns at 90 cells, list/preview at 55 cells, list only below that). The directory stays at the top. There is no duplicate file footer: the global Cosmos status bar shows selected filename, size, colored permissions, numeric owner/group, percentage and position instead of the directory path. Wide layouts show more metadata; narrow layouts prioritize position. `style.py` classifies directories, links, executables, images, documents, archives, media and source files. Links have their own amber role and show their literal target, including dangling links. Its RGB/background and cell content use the existing Cosmos renderer, palette and event path. There is no second terminal output owner. The global status mode is FILES.

Keys are registered under `files.*` in shared Keybindings, help and Ctrl+P Actions: arrows/hjkl navigate, Enter opens, Home/End and PageUp/PageDown move through entries, . toggles hidden entries, s cycles sort, / opens the pane-local bottom filter, ? shows help. Mouse clicks select rows and the wheel moves selection. Space toggles a file in the multi-selection and advances; V toggles all visible entries. Selected paths remain selected while filtering, but file operations act only on the visible selection (or the current item if none is visible). S opens a sort chooser; R reverses ordering; Ctrl+R refreshes cached metadata.

Supported files open through the existing Reader; closing it returns to the originating file list. Other regular files use the existing external application route. Errors become notifications instead of terminating the UI. File browsing never changes the shell's current directory.

## Operations and settings

All commands are exposed through `files.*` Keybindings, contextual Ctrl+P Actions and help. `y` copies paths into the client-local file clipboard; `x` marks them for moving; `p` pastes into the currently displayed directory. `a` creates a file, `A` a directory, and `r` renames the current item through the pane-local bottom input. Names must be a single component. `d` opens a confirmation with Cancel selected by default, then moves items to the host user's FreeDesktop home Trash with `.trashinfo` metadata. Permanent deletion is not exposed. Symlinks are copied/moved as links, not followed. Collisions fail without overwriting; batch operations can partially complete before a later I/O failure, and there is no transactional rollback or undo UI.

`operations.py` implements Cosmos-owned filesystem mutations; it does not claim these are extracted Yazi task-engine code. Same-filesystem moves use Linux no-replace rename; cross-filesystem moves copy then remove the source. A single client operation runs off the UI thread; completion/errors use the notification event API. Progress/cancellation and cross-client task coordination are not provided yet. For cross-device Trash, an interrupted copy can require manual cleanup. File clipboard state belongs to the client and is not retained after detach.

`t` opens a Cosmos terminal window in the displayed directory; `g` opens a Cosmos Agent window there, using `COSMOS_OPENCODE` or OpenCode on PATH. These explicit actions do not change the source Bash cwd or replace the file view.

Settings → Files persists `files_icons` (default false; enabled icons require a Nerd Font) and `files_border` (`none`, `dividers` default, or `frame`). Frame junctions meet the outer border. File types share Cosmos semantic colors; links use a separate color from directories.

## State and implementation boundary

The internal pane presentation metadata uses `kind = "files"`, `path`, `cursor`, and optional `filter`, `show_hidden`, `sort`, `reverse` and `selected` (absolute paths). It is retained in the existing Tmux pane metadata, not a Yazi child process. Native sorting and listing are separate from presentation so the future sidebar can reuse them.

This is not Yazi feature parity. Task progress/cancellation, archive/plugin/VFS capabilities and the collapsible left dock remain undelivered. The right-hand preview currently handles bounded text and directory names; rich previews remain to be integrated with the shared Reader. No plugin or file-operation API is declared public by this stage.
