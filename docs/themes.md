# Terminal and interface themes

Open **Settings → Theme** (`Leader p`, filter Theme, Enter). The upper half contains two lists:

- **Terminal content**: Follow terminal (default), Ubuntu · Tango, Cosmos Dark, Cosmos Light, Solarized Dark, Solarized Light, Gruvbox Dark, Nord, plus user files.
- **Cosmos interface**: Cosmos Dark (default), Cosmos Light, Cosmos Midnight, Cosmos Paper, plus user files.

The full-width lower preview shows terminal defaults/ANSI swatches, interface roles, the themed COSMOS wordmark and its four icon colors. Selection only changes the preview. Use Tab / Shift+Tab to move between lists and controls, arrows to select, and **Ctrl+S** or the ✓ button to save. The × button or Escape cancels without changing the current workspace. Press **r** in the Theme panel to rescan theme files without restarting Cosmos.

## Color boundaries

Follow terminal keeps native default foreground/background and ANSI/indexed colors. It follows the terminal emulator displaying Cosmos, including the local terminal at the other end of SSH, without querying GNOME settings or requiring desktop services. Thus a Bash pane launched from your Ubuntu terminal retains that terminal's palette. The Ubuntu preset is a fixed Tango palette with `#300A24` background, not an import of a customized GNOME profile.

Terminal presets change default foreground/background and the first 16 ANSI colors. Application-provided truecolor and indexed colors 16–255 stay explicit. Consequently an application with its own hardcoded truecolor theme may still require its own settings. Syntax highlighting and fonts are not rewritten. These settings apply to all terminal panes in this Cosmos service, rather than assigning themes per process or per pane.

Cosmos UI colors remain independent: popups, menus, borders, status bar and input-method surfaces use their semantic roles. Readers retain their own interface/bitmap colors rather than receiving terminal palette remapping. Textual's automatic ANSI-to-truecolor filter is disabled to preserve native terminal colors.

## Theme folder and dynamic loading

Built-in themes are TOML files in `themes/` beside the Cosmos executable. User themes are read from:

```text
${XDG_CONFIG_HOME:-~/.config}/cosmos/themes/*.toml
```

The file name without `.toml` is the id stored in configuration. A user file with the same id overrides the built-in theme of that kind. Files are validated and loaded when the UI starts and whenever the Theme panel opens or **r** is pressed; invalid files are skipped and listed below the preview. The `themes/templates/` directory contains `terminal.toml` and `cosmos.toml` starting points; it is not loaded as a theme.

Terminal theme example:

```toml
kind = "terminal"
name = "My Terminal"
fg = "#D8DEE9"
bg = "#1E222A"
ansi = [
  "#1E222A", "#E06C75", "#98C379", "#E5C07B",
  "#61AFEF", "#C678DD", "#56B6C2", "#ABB2BF",
  "#5C6370", "#E06C75", "#98C379", "#E5C07B",
  "#61AFEF", "#C678DD", "#56B6C2", "#FFFFFF",
]
```

Cosmos theme example:

```toml
kind = "cosmos"
name = "My Cosmos"
light = false

[colors]
bg = "#14161E"
base = "#1E212C"
fg = "#CDD2DC"
mute = "#7A8092"
acc = "#62A0E6"
accl = "#A0CDFA"
on = "#10121A"

[logo]
foreground = ["#FFE6A3", "#16966A"]
background = ["#3A3120", "#103027"]
mode = "diagonal"
steps = 8
```

The `[logo]` table controls four colors: the foreground gradient start/end and the background gradient start/end. The COSMOS wordmark uses the foreground pair with `mode` (`vertical`, `horizontal`, `diagonal`, `radial`) and `steps`; the status-bar start button follows the same foreground pair while using the background pair. Omitting `[logo]` uses the built-in dark-theme gradient. `light = true` selects the light interaction class and light status-bar secondary backgrounds.

## Configuration

The coordinator persists `terminal_theme` and `theme` as theme ids, independently. Existing configurations default to `inherit` and `dark`:

```toml
terminal_theme = "inherit"
theme = "dark"
```

Ids must be safe file stems (letters, digits, `-`, `_`; at most 64 characters). A coordinator predating the theme catalog must be restarted before it can save arbitrary ids; detach clients, run `cosmos stop`, then reopen Cosmos. Tmux applications remain running; coordinator-managed Mods stop. Merely opening a new terminal does not replace the persistent coordinator.

`features/theme/catalog.py` discovers and validates theme files; `features/theme/palettes.py` resolves terminal colors; `features/theme/panel.py` hosts the two-list preview transaction; `features/theme/controller.py` applies interface roles; `ui/logo.py` renders the themed wordmark. `render/surface.py` applies terminal colors only to application cells; pane borders remain Cosmos UI. Theme changes invalidate terminal surface state without resizing the PTY.
