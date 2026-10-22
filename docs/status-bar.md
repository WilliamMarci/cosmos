# Default status bar

The bar is composed by `features/status/controller.py` and `features/status/bar.py`. Segments are separated by background colors and spacing, never literal `|` characters.

- Left: clickable start button, then the current Tmux window index in superscript and its name. The index remains the actual backend index; it is not renumbered.
- Center: registered Mod status widgets, shown at the screen center when they fit without overlapping the left or right groups.
- Right: reader details when applicable, path and Git branch when available, independently clickable input language and width, then local time/date (`HH:MM Mon DD`). Home paths are abbreviated as `~`.

Directory/program and Git branch are refreshed on pane changes and at most once every two seconds. Git uses read-only `symbolic-ref`; non-repositories and detached HEAD have no branch label. Long path/details are dropped before essential controls; tight widths truncate remaining text. The bar respects the existing visibility setting.

## Start button

`Leader m` and clicking the button open the same COSMOS start menu regardless of its current label. The active pane controls the label:

- `COSMOS`: normal terminal, default gradient text `#FFD166` → `#168A70` over a dark gradient background `#3A3120` → `#103027`. An explicit `status_colors.cosmos` overrides it with a solid color.
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

The reader footer keeps its filename on the left and aligns collection/page index, actual rendered scale percentage and raster pixel size on the right, before its collapse control. Raster dimensions for PDF refer to the rendered page bitmap. The status bar repeats available reader metadata in its right group; it favors that over long paths at narrow widths.
