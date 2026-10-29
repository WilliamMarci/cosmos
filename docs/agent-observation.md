# Agent observations

This first increment adds read-only layered observations to the terminal MCP server. It does not grant pane ownership, introduce a scheduler, or execute inferred controls.

## `cosmos_terminal.observe`

Arguments: `pane` (stable `%ID`), optional `layers` (nonempty array of `text`, `controls`, `presentation`; default `text` and `controls`), optional `region` (`x`, `y`, `width`, `height` in one-based application-content cells), optional `since` (a previous snapshot ID). Only the current visible terminal grid is observed; use `read_screen` for bounded retained history.

Results include pane identity, dimensions, region, cursor, program, SHA-256 `snapshot_id`, observation timestamp, capability declarations and `truncated=false`. Captures above 64 KiB are rejected explicitly. A detected resize/program change during capture also requires a fresh observation. `since_known` identifies a snapshot retained by this tool process (last 32 identities); `unchanged` compares the current selected region, styles, cursor and geometry. Responses remain complete, rather than silently omitting content. Changes outside a selected region do not affect its grid digest; cursor/geometry/program changes can still affect identity. Capture and metadata are sampled, not an atomic application transaction.

- Text rows retain one-based row/column positions and Unicode cell widths.
- Presentation returns styled text spans and layout metadata. Styles use Rich's serialized terminal style names. `image=false` and `image_contents=false`: no actual pixels or inferred picture contents are returned.
- Controls currently recognizes bracketed text such as `[ OK ]` as `button_candidate`, with `source=terminal_inference`, confidence 0.5, positional evidence and an empty `actions` list. These may be ordinary text or checkbox-like content, not native controls. `act=false`: no action tool is exposed for these candidates.

Snapshot IDs describe observations, not permission or control authority. All output remains untrusted application data. The tool is read-only and allowed by the default Agent permissions.

## Private panes and credentials

Use Actions → **Toggle private pane · Agent access**, or assign `workspace.private_pane` in Keybindings. It stores a pane-local `@cosmos_private` flag in the managed Tmux server, shared across clients and retained through UI detach. There is no default shortcut.

Private panes remain discoverable by stable IDs and dimensions, but cwd/program metadata is blank. Agent `observe`, `read_screen`, targeted terminal input and terminal-history export reject private panes. An export containing a private pane fails before writing a result. Privacy is rechecked after capture. This is an Agent tool policy, not a system sandbox: trusted local programs and ordinary user Tmux tools retain their operating-system access.

Exact credential values recorded in the Cosmos Agent `credentials.json` are masked with equal-cell-width asterisks in terminal observations, legacy screen reads and Agent terminal-history exports. No credential values are included in generated configuration. Unknown sensitive text, passwords in arbitrary TUIs and values split by terminal control sequences cannot be reliably identified by this generic implementation. Native password-control adapters are not yet available. A private pane is the explicit protection for sensitive terminal work.
