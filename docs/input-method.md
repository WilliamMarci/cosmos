# Input method and keyboard preview

## Input method

`Leader i` toggles Chinese/English for the current Cosmos client. It is registered as `global.ime_toggle` and can be rebound. **Input width · Half / Full** in Ctrl+P Actions toggles width (`global.ime_width`, no default key). The status bar's right edge shows `中/En` and `●/◐` (full/half width); clicking language or width toggles that setting. Hidden status bars stay hidden.

The engine is real librime with the discovered Rime schema (`rime_ice` by default), not a demo dictionary or a desktop IBus connection. Enablement and width are client-local. Each pane keeps its own Rime composition when focus changes; Cosmos input fields have separate contexts. Closing the client destroys its compositions without sending them to applications. Session applications keep running.

While composing, the two-row overlay shows preedit and numbered candidates near the input cursor. Space or candidate digits commit text without adding Return; arrows and PageUp/PageDown are passed to Rime for candidate navigation, Backspace edits, and Escape cancels. Candidate cells can be clicked. The overlay is clamped inside the pane or UI viewport and moves above the cursor when needed. It uses `UIFrame` / `CellSurface` on the insert/cover layer and never writes terminal escape sequences independently or resizes the pane. Very small viewports may clip candidates; paging remains available.

Committed text goes to the captured pane using the existing paste adapter, or directly into the focused Cosmos Input. Viewer navigation, copy-mode, password fields and non-editable views bypass composition. Leader and global shortcuts are resolved before IME input. Ctrl+Space remains available to applications. Pasted text bypasses phonetic conversion. English full-width mode converts printable ASCII to full-width characters; control shortcuts pass through.

## Engine and data discovery

- Library: `COSMOS_RIME_LIBRARY`, then package `lib/librime.so.1`, then system librime.
- Plugins: `COSMOS_RIME_PLUGINS`, package `lib/rime-plugins`, then the system multiarch `rime-plugins` directory.
- Data: explicit `COSMOS_RIME_DATA`; otherwise `$XDG_CONFIG_HOME/ibus/rime`, `fcitx5/rime`, `fcitx/rime`, `cosmos/rime`, then package `share/rime-data`. XDG config defaults to `~/.config`. Existing desktop directories take priority over Cosmos data.
- Schema: explicit `COSMOS_RIME_SCHEMA`, then the selected schema in `user.yaml`, then available `rime_ice`, then the first schema in default configuration. Data must already contain the selected compiled `build/SCHEMA.schema.yaml` and its dictionaries, Lua/OpenCC resources and custom configuration. Cosmos does not deploy or rewrite that source tree.

User databases and logs live under `$XDG_STATE_HOME/cosmos/rime` (default `~/.local/state/cosmos/rime`). Resource links exclude desktop user databases and installation state. Learning uses locked profile slots, so simultaneous Cosmos clients do not open one LevelDB writer concurrently; the next client reuses a free profile. Existing desktop learning databases are not imported. Librime initialization is lazy and runs off the UI event loop. Missing libraries, plugins or data produce a notification when enabling IME; ordinary terminal input continues working.

The ctypes adapter follows the integer-Bool version of the [official librime C API](https://github.com/rime/librime/blob/master/src/rime_api.h), checks the API prefix size, initializes versioned structures and frees commit/context allocations. No IBus daemon is required.

## Keyboard preview

The 64-column, five-row layout derives from `design/cosmos_keys.py`, using Cosmos semantic colors. Help places it below the shortcut list when the viewport can fit both. In keybinding settings it appears beneath the list, above the bottom filter, and follows the selected command. The key editor updates it as its binding text changes. Smaller viewports hide it automatically and restore it after enlargement.

The preview expands Leader to the configured Ctrl+B/Ctrl+A stroke and maps shifted punctuation to physical keys plus Shift. Help highlights the union of its listed bindings; keybinding settings highlight the selected action's keys. This is a preview, not yet a mouse-based keybinding capture editor.

## Distribution boundary

The launcher supports package-local shared libraries through `lib/`. The current foundation archive does **not** yet bundle the full Rime runtime and dictionary data. It therefore requires the system dependencies or explicit paths above for IME. A self-contained Rime bundle, dependency/license inventory and clean-machine verification remain distribution work; copying only `librime.so` is insufficient. No claim of portability to machines without Rime is made for the current archive.
