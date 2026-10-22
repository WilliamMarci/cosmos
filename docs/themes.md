# Independent terminal and interface themes

Open **Settings → Theme** (`Leader p`, filter Theme, Enter). The upper half contains two lists:

- **Terminal content**: Follow terminal (default), Ubuntu · Tango, Cosmos Dark, Cosmos Light.
- **Cosmos interface**: Cosmos Dark (default), Cosmos Light.

The full-width lower preview shows terminal defaults/ANSI swatches and interface roles together. Selection only changes the preview. Use Tab / Shift+Tab to move between lists and controls, arrows to select, and **Ctrl+S** or the ✓ button to save. The × button or Escape cancels without changing the current workspace.

## Color boundaries

Follow terminal keeps native default foreground/background and ANSI/indexed colors. It follows the terminal emulator displaying Cosmos, including the local terminal at the other end of SSH, without querying GNOME settings or requiring desktop services. Thus a Bash pane launched from your Ubuntu terminal retains that terminal's palette. The Ubuntu preset is a fixed Tango palette with `#300A24` background, not an import of a customized GNOME profile.

Terminal presets change default foreground/background and the first 16 ANSI colors. Application-provided truecolor and indexed colors 16–255 stay explicit. Consequently an application with its own hardcoded truecolor theme may still require its own settings. Syntax highlighting and fonts are not rewritten. These settings apply to all terminal panes in this Cosmos service, rather than assigning themes per process or per pane.

Cosmos UI colors remain independent: popups, menus, borders, status bar and input-method surfaces use their semantic roles. Readers retain their own interface/bitmap colors rather than receiving terminal palette remapping. Textual's automatic ANSI-to-truecolor filter is disabled to preserve native terminal colors.

## Configuration and implementation

The coordinator persists `terminal_theme = "inherit" | "ubuntu" | "cosmos-dark" | "cosmos-light"` separately from the existing `theme = "dark" | "light"` field. Existing configurations default to `inherit` and `dark`.

```toml
terminal_theme = "inherit"
theme = "dark"
```

A coordinator predating `terminal_theme` must be restarted before it can save this field; detach clients, run `cosmos stop`, then reopen Cosmos. Tmux applications remain running; coordinator-managed Mods stop. Merely opening a new terminal does not replace the persistent coordinator.

`features/theme/palettes.py` resolves terminal defaults/ANSI colors, `features/theme/panel.py` hosts the two-list preview transaction, and `features/theme/controller.py` applies interface roles. `render/surface.py` applies terminal colors only to application cells; pane borders remain Cosmos UI. Theme changes invalidate terminal surface state without resizing the PTY.
