# UI package Mods — host API v1

UI package Mods are trusted Python code loaded by each Cosmos client. Existing process Mods retain their Rust lifecycle/RPC SDK. Both are managed from Settings → Mods, with UI packages labelled “UI Mod”. This API adds host UI callbacks without hardcoding calendar or other business behavior in the application.

## Package discovery and relocation

A package contains `mod.toml`, a Python entry and all its private files. The entry may use relative imports. Default discovery scans `mods/*/mod.toml` beside the Cosmos entry. Optional absolute `ui_mod_paths` accepts either a package directory or a directory containing packages. Later configured paths override a bundled package of the same ID.

```toml
# Cosmos config.toml root fields, before any table:
ui_mod_paths = ["/absolute/path/to/calendar"]

[ui_mods.calendar]
enabled = true
notifications = false
```

Updating root settings via settings.replace applies to all clients. Editing config.toml on disk requires coordinator reload/restart, as with other file edits. Settings → Mods → Rescan UI packages discovers newly copied packages in the current paths. Moving a package requires updating its path (or placing it in the default mods directory); there is no absolute-path dependency in calendar's source.

Manifest:

```toml
id = "calendar"
name = "Calendar"
api_version = 1
entry = "__init__.py"
enabled_by_default = true
permissions = ["notifications"]
```

Manifests are limited to 8 KiB. IDs contain ASCII letters/digits, `_` or `-`; entries must be files inside their package. The current permission vocabulary is `notifications`. Source is imported only when enabled. `activate(api)` registers components and may return a synchronous cleanup callable. Disabling invokes cleanup, removes status callbacks and closes the Mod's popup. Import/activation failures are logged and reported through the host operation-error notification path, not a separate error UI.

## Public Python API

Import host primitives from `cosmos_tui.mods.api`: ModPopup, Frame, Static, Text, Binding. API v1 deliberately exposes a small in-process UI interface:

- `api.id`: package owner ID.
- `api.palette`: a copy of the current Cosmos role palette.
- `api.status_action("clock", callback)`: register a click callback on the date/time segment. Only one owner may occupy the slot. Currently clock is the supported slot.
- `api.popup(screen)` / `api.toggle_popup(screen)`: show/toggle an owned popup. ModPopup is transparent outside its Frame, anchors above the right status area, retains the reader image and masks only the popup rectangle with alpha transparency. It does not resize a PTY.
- `api.commands([(name,label,keys,target), ...])`: register normal keybinding entries under `mod.<id>.<name>` and context `mod.<id>`. They appear in Keybindings → Mods; overrides use the normal settings map. A ModPopup's target actions dispatch to its own action methods. Disabled/unavailable packages retain dormant configured bindings.
- `ModPopup.action_help`: show shared shortcut help for the Mod context; packages may bind `?` to `help`.
- `await api.notify(text, **metadata)`: publish through Cosmos's notification event API. Source is assigned as `mod.<id>`; level/actions/ttl/session metadata follows notifications.md.

Do not depend on private API fields or import business logic from the host. The supplied calendar package demonstrates only public APIs.

## Enablement and notification permission

Settings → Mods → package provides separate Enabled and Notification permission choices. Enablement is shared configuration; the actual UI module runs in each attached client. A package's enabled_by_default is used only when no saved enabled policy exists. The bundled calendar is enabled by default.

Notification permission defaults to **Off**, independent of enablement. `api.notify` requires a loaded/enabled owner, a declaration in the manifest and the saved permission grant. The host sends a reserved ui_mod owner marker, and the coordinator independently checks the saved grant and enablement at publication time (including changes from another client). Revoking it affects existing API objects immediately; disabling the package also blocks sends. Normal host errors can still be reported by Cosmos itself. Calendar does not publish periodic notifications or reminders by default.

These are supported host-API permissions, not an OS sandbox: packages are installed trusted Python programs in the client process. The older external-process SDK/RPC path is not turned into a sandbox or silently subjected to this UI-package policy. No filesystem/network isolation is promised.
