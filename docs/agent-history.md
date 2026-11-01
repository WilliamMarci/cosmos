# Agent retained terminal history

`cosmos_terminal.read_history(pane, limit=100, query=None, cursor=None)` reads
Tmux's retained scrollback above the current viewport. It does not move the user's
scroll position or acquire input ownership. The default Agent policy allows it.

The first call captures at most 20,000 retained rows and keeps at most 2 MiB of
redacted UTF-8 text. `query` is an optional literal, case-insensitive substring,
not a regex or shell expression. Queries containing known Cosmos credentials are
rejected. Snapshot rows are immutable even while the application continues writing.
Four snapshots are retained per authenticated conversation for up to five minutes.

Responses contain `pane`, `snapshot_id`, sampled `history_size`,
`history_truncated`, `query`, `rows`, `next_cursor`,
`current_screen_included: false` and the coordinate-space label. Each row has a
negative snapshot-relative `line`, `text`, and `truncated` flag. Indices identify
text in the captured scrollback, not live mouse/input coordinates. Capture is a
live sample rather than an atomic application transaction.

Pages start with the newest matching rows, displayed chronologically within each
page. Pass `next_cursor` and the same pane to obtain older rows. `limit` is 1–200;
text per page is bounded to 16 KiB. A very wide individual row may be truncated
explicitly. Reusing a cursor reproduces the same page with the same limit.
Changing the query needs a fresh snapshot; omit it when following a cursor.
`next_cursor: null` means no more matching rows in this snapshot, not necessarily
that Tmux has no older retained output. `history_truncated` reports capture limits.

Privacy is checked before capture, after capture and on every continuation.
Expired/foreign-conversation cursors, closed/private panes or a changed Tmux server
are rejected. Already evicted Tmux output cannot be recovered. Use `read_screen`
for current viewport text and `export_history` for a larger private session export.
This API is separate from Bash command history and model conversation export.
