# Default status bar

The bar is composed by `features/status/controller.py` and `features/status/bar.py`. Segments use distinct background levels and configurable separators. Defaults follow the Cosmos palette, rather than copying an external editor theme.

- Left: clickable start button, then the current Tmux window:pane position indices in normal-size digits and the window name on a separate background level. The index remains the actual backend index; it is not renumbered.
- Center: registered Mod status widgets, shown at the screen center when they fit without overlapping the left or right groups.
- Right by default: a slightly brighter gray path block and a separate darker Git branch block in the accent foreground when available, independently clickable input language and width, then local time/date (`HH:MM Mon DD`). Home paths are abbreviated as `~`.

Directory/program and Git branch are refreshed on pane changes and at most once every two seconds. Git uses read-only `symbolic-ref`; non-repositories and detached HEAD have no branch label. Paths retain their most recent components and prefix omitted components with `…/`; remaining long text is shortened from the left with an ellipsis. Essential clock/IME controls reserve space before the path. Tight widths truncate remaining text. The bar respects the existing visibility setting.

## Start button

`Leader m` and clicking the button open the same COSMOS start menu regardless of its current label. The active pane controls the label:

- `COSMOS`: normal terminal, default gradient text `#FFE6A3` → `#16966A` over a dark gradient background `#3A3120` → `#103027`. These four colors come from the selected Cosmos theme's `[logo]` table (foreground start/end and background start/end); the wordmark uses the same foreground pair with its `mode` and `steps`. An explicit `status_colors.cosmos` overrides the button with a solid color.
- `IMAGE`: bitmap viewer, green background.
- `DOC`: PDF (and future EPUB/Markdown viewer surfaces), green background.
- `AGENT`: foreground `opencode`, `claude`, or `codex`, magenta background.
- `FILES`: foreground `yazi`, red background.

Other mode foregrounds default to terminal bright white. These are independent from the main dark/light palette. Native program names and viewer state determine the label, not inactive panes or window titles. FILES/DOC classification does not imply the planned Yazi/EPUB/Markdown modules have been implemented.

Set optional colors in `$XDG_CONFIG_HOME/cosmos/config.toml` (default `~/.config/cosmos/config.toml`):

```toml
[status_colors]
cosmos = "blue"
image = "green"
doc = "green"
agent = "magenta"
files = "red"
foreground = "bright_white"
```

The example deliberately overrides the default COSMOS gradient with solid blue; omit `cosmos` to retain the gradient. Each value accepts `#RRGGBB` or one of `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`, `bright_white`. Unspecified roles use defaults. File changes apply when the coordinator loads the configuration; the current coordinator must support `status_colors` before saving these fields through settings RPC. UI colors react to the service's current settings. There is no color editor in the compact settings panel yet.

## Input indicators and reader information

`中` / `En` toggles Chinese/English. `●` / `◐` toggles full-width/half-width; the full circle means full-width. Each has its own hit region, including while a Cosmos modal is open. They use monochrome terminal glyphs.

The reader footer keeps its filename on the left and aligns collection/page index, actual rendered scale percentage and raster pixel size on the right, before its collapse control. Raster dimensions for PDF refer to the rendered page bitmap. The global Cosmos status bar does not repeat page/pixel/zoom details; they remain local to the reader footer.

## Path and separator settings

Settings → Status bar provides left/right choice controls for these shared fields:

- `status_path_depth`: recent path components, default 3; 0 shows all, configuration permits 0–32.
- `status_path_max_length`: path block content width in terminal cells, default 40, range 8–240. The bar reduces this further when space is tight.
- `status_path_align`: left, center, or right (default). The center block shares available space with registered Mod widgets.
- `status_separator`: powerline (default ``), capsule (`` / ``), slash (`╱` / `╲`), vertical (`│`), or none. Left-aligned blocks point right (``); right-aligned blocks point left (``). Center blocks use outward edges. Capsule blocks use rounded outer edges. Every seam uses the immediate left/right background colors; the COSMOS gradient contributes its nearest endpoint, including explicit solid mode colors. Select another style if the terminal font lacks Powerline glyphs.

These fields are validated and persisted through settings.replace. Existing configuration files load the defaults. Upgrading a running coordinator requires a restart before the fields can be saved.

The clock segment is a generic UI-Mod action slot. The bundled calendar package registers it and displays its own popup; the status bar contains no calendar logic. Disabling that package removes the click action. See ui-mods.md for relocation and notification permissions.

Git branch names have their own 24-cell maximum (including a trailing ellipsis), reduced further on narrow terminals. They do not consume the configured path-length limit. Both blocks follow path alignment and the chosen separators, with seam colors taken from the adjacent backgrounds.

User-facing pane numbers and Switch labels use current position indices; sessions use their names. Stable session/window/pane IDs remain internal click and command targets, so splits, closes and renumbering never redirect an existing selection to a different pane.
