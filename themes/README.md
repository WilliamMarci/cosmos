# Cosmos themes

Each `*.toml` file in this directory or in
`${XDG_CONFIG_HOME:-~/.config}/cosmos/themes/` is loaded dynamically when the
Theme panel opens. The file stem is the id used by `theme` or
`terminal_theme` in `config.toml`; a user file with the same stem overrides the
built-in file.

- Terminal themes use `kind = "terminal"` and define `fg`, `bg` and sixteen
  `ansi` colors.
- Cosmos interface themes use `kind = "cosmos"`, a `[colors]` table, and a
  `[logo]` table containing two foreground colors and two background colors.
  The optional `mode` (`vertical`, `horizontal`, `diagonal`, `radial`) and
  `steps` values control the generated wordmark gradient.

Start from `templates/terminal.toml` or `templates/cosmos.toml`. Invalid files
are skipped and listed in the Theme panel. Press `r` in the Theme panel to
rescan the folders without restarting Cosmos.
