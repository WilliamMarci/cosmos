# Settings controls and shortcut editing

Settings is a compact pop window. The frame and its list share the UI base color; focused lists and inputs do not add Textual's default background tint. Pop-window backgrounds and background-tint are transparent, including About, Theme and the shortcut editor. The selected row uses the Cosmos highlight color.

## Navigation and values

- Up/Down selects an item.
- Enter opens a submenu or invokes the selected action. On a choice row, Enter advances its value.
- `q` or Escape returns to the parent menu, or closes the root. `,` returns to the parent; `.` opens a selected submenu/editor. These keys are navigation keys in the settings list, including while its filter is focused.
- Left/Right cycles the selected choice. The left label stays fixed; the current value and `◂` / `▸` controls are right aligned. Clicking the arrows cycles backward/forward. Values wrap.

Status path depth/length/alignment/separators, cache size, maximum image size, adjacent-page prefetch, mouse mode, mouse passthrough, candidate number glyphs, Leader, interface theme, status visibility, reduced motion and notification enablement use this control. Other entries remain actions/submenus. Mouse mode stays client-local; mouse passthrough uses the shared `mouse_passthrough` field so all clients see the same selection, while the other choices use their existing shared configuration fields.

Shared choices write settings.replace and read settings.get back before accepting the change. A rejected/unretained value stays unchanged. Persistence and operation failures go through the shared action-error handler and publish an error notification; they do not add an error block to the settings window. Keybinding syntax validation remains next to its input. Before opening the UI, startup checks the running coordinator capabilities and settings fields, including reader cache controls, and provides a restart command if they are incompatible. Opening a new terminal alone reconnects to the same background service.

## Shortcut names and phases

Shortcut settings show the action name on the left and its actual current bindings in muted gray on the right. Hints come from the shared registry and overrides; Leader expands to the configured Ctrl+B/Ctrl+A. Saving an editor refreshes the parent list. Relevant frame headings use the same current binding formatter.

The editor uses one row per alternative binding, with two explicit fields:

- A direct chord such as `ctrl+x` belongs in the first field; the second is empty. `+` joins keys pressed together.
- A Leader sequence uses `leader`, `leader2` or `leader3` in the first field and e.g. `p` in the second. The arrow denotes first press, then next press.
- L1/L2/L3 buttons select a prefix preset. Defaults are Ctrl+B / Ctrl+A / Ctrl+M; Settings → Keybindings → General & menus configures the presets, including Off for the additional two.
- `+` button adds an alternative row; `✓` / Enter saves; `↺` restores defaults. All empty rows also restore defaults.
- Comma is no longer an alternative/stage delimiter. A literal `,` in a field is normalized to `comma`; the same applies to `.`, `+` and `?`.

The keyboard preview follows both fields and distinguishes first/next press. Ctrl+M followed by X can be stored as `leader3+x`. Arbitrary unnamed multi-stage sequences are not supported; select one of the three presets. Additional prefixes are reserved only when at least one action uses them. Legacy terminals may encode Ctrl+M as Enter: plain Enter is preserved, and Leader3 requires a distinct Ctrl+M key report or a different configured chord. Conflicts and incomplete sequences are reported inline.

The saved configuration remains an array of normalized bindings, e.g. `['leader+p', 'leader2+x', 'leader3+x', 'ctrl+g']`. This change is in the editor presentation, not a new RPC format. See ui-api.md for the configuration contract.

## Internal row interface

`ui/settings.py` contains `SettingRow(row)`. A choice row contains label, key, value, choices (value/label pairs) and optional local scope. It posts `SettingRow.Cycle(row, direction)` for arrow clicks; the settings feature owns persistence and error handling. A binding row uses a separate hint field rendered with the muted role color. This is a host Python control, not an external Mod RPC extension.

Reader 新增 viewer_disk_cache_mb（默认 512）、viewer_pdf_edge（默认 2400）和 viewer_pdf_page_mb（默认 32）。Settings → Mods 同时列出进程 Mod 和可移动 UI packages；UI 包子菜单分别管理启用与通知权限，缺省不授予通知。详见 ui-mods.md。


## Rich Reader defaults

Settings → Reader provides Default document columns (`viewer_rich_columns`: `auto`, `1`, `2`, `3`; default `auto`), Default reading mode (`viewer_rich_mode`: `pages` / `scroll`; default `pages`), Inline image maximum rows (`viewer_inline_image_rows`: 1–32; default 8), and Icon maximum edge (`viewer_icon_max_px`: 0–256 pixels; default 64, 0 disables icon classification). These use the standard left/right choice controls and are saved by the coordinator.

New/unconfigured rich-document panes use the current column/mode defaults. Changing the pane's upward Options menu or its Actions creates a pane override; subsequent changes to defaults do not overwrite that pane's selection. Icon thresholds follow current settings. Image height follows the global default unless the pane's Options menu supplies an override. The pane-local line spacing control offers 0–3 (0 removes generated spacer rows) without adding gaps inside tables or images. They invalidate the reflow cache. See rich-reader.md for keyboard controls and clipboard limitations.

An already running coordinator from before these fields were added must be restarted after detaching clients; its Tmux applications are retained. Existing configuration files acquire the new defaults automatically.
