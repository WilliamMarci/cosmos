# Settings controls and shortcut editing

Settings is a compact pop window. The frame and its list share the UI base color; focused lists and inputs do not add Textual's default background tint. Pop-window backgrounds and background-tint are transparent, including About, Theme and the shortcut editor. The selected row uses the Cosmos highlight color.

## Navigation and values

- Up/Down selects an item.
- Enter opens a submenu or invokes the selected action. On a choice row, Enter advances its value.
- `q` or Escape returns to the parent menu, or closes the root. `,` returns to the parent; `.` opens a selected submenu/editor. These keys are navigation keys in the settings list, including while its filter is focused.
- Left/Right cycles the selected choice. The left label stays fixed; the current value and `◂` / `▸` controls are right aligned. Clicking the arrows cycles backward/forward. Values wrap.

Cache size, adjacent-page prefetch, mouse mode, candidate number glyphs, Leader, interface theme, status visibility, reduced motion and notification enablement use this control. Other entries remain actions/submenus. Mouse mode stays client-local; the other choices use their existing shared configuration fields.

Shared choices write settings.replace and read settings.get back before accepting the change. A rejected/unretained value stays unchanged and an inline error explains the failure. This also reports an older coordinator that cannot retain a newer field, instead of pretending the setting changed.

## Shortcut names and phases

Shortcut settings show the action name on the left and its actual current bindings in muted gray on the right. Hints come from the shared registry and overrides; Leader expands to the configured Ctrl+B/Ctrl+A. Saving an editor refreshes the parent list. Relevant frame headings use the same current binding formatter.

The editor uses one row per alternative binding, with two explicit fields:

- A direct chord such as `ctrl+x` belongs in the first field; the second is empty. `+` joins keys pressed together.
- A Leader sequence uses `leader` in the first field and e.g. `p` in the second. The arrow denotes first press, then next press.
- `+` button adds an alternative row; `✓` / Enter saves; `↺` restores defaults. All empty rows also restore defaults.
- Comma is no longer an alternative/stage delimiter. A literal `,` in a field is normalized to `comma`; the same applies to `.`, `+` and `?`.

The keyboard preview follows both fields and distinguishes first/next press. General custom prefixes such as Ctrl+M followed by X are not registered by this editor; two-stage runtime bindings currently require the configured Leader. Conflicts and incomplete sequences are reported inline.

The saved configuration remains an array of normalized bindings, e.g. `['leader+p', 'ctrl+g']`. This change is in the editor presentation, not a new RPC format. See ui-api.md for the configuration contract.

## Internal row interface

`ui/settings.py` contains `SettingRow(row)`. A choice row contains label, key, value, choices (value/label pairs) and optional local scope. It posts `SettingRow.Cycle(row, direction)` for arrow clicks; the settings feature owns persistence and error handling. A binding row uses a separate hint field rendered with the muted role color. This is a host Python control, not an external Mod RPC extension.
