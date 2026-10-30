# Pane input ownership

This increment implements cross-process input ownership and user revocation. It does not yet implement the shared Taking over/PAUSED top row, animated pointer, model-run cancellation, monitor wakeups or persistent task scheduler.

## Tools

- `control_status()` returns controlled panes, task labels and states (`active`, `paused`, `ready`), without ownership tokens.
- `acquire_control(pane, snapshot_id, task)` requires a snapshot observed by the same MCP connection, re-observes the same region, and rejects changed snapshots. It returns a cryptographically random token. Another owner cannot replace it, and a manually paused task cannot reacquire until a user resumes it.
- `control_input(pane, token, kind, arguments, snapshot_id=None)` accepts `send_text`, `send_keys` or `mouse` using the existing terminal input argument names. Tokens belong to one MCP connection and pane. Mouse requires a fresh observation ID covering its target cell. Tmux server PID, pane window and dimensions are checked against acquisition; layout changes require a fresh acquisition. Mouse additionally revalidates its observation before input. These are sampled checks, not atomic application transactions.
- `release_control(pane, token)` ends the owner's task, including one paused with that token. It does not send Ctrl+C, close a pane or stop a terminal program.

All mutating tools retain the native Agent confirmation policy. Ownership does not grant model permissions. `control_input` returns `delivery=delivered`, `action_complete=false`, `task_complete=false`: downstream evidence is still required.

## Human input and recovery

A physical non-modifier key in a workspace terminal, pasted text or a click on a terminal pane pauses that pane's control task before normal UI/terminal handling. Mouse forwarding (including wheel and drag) also revokes ownership. This applies when keyboard passthrough is enabled. The first transition emits a notification; repeated input does not repeat it.

A pause marker is published before waiting for an in-flight sender's lock. Controlled input checks it immediately before dispatch; queued/stale tokens fail. Input already dispatched cannot be recalled. This is not a hard real-time guarantee and does not cancel a native model request already running. The Agent prompt requires returning to the user after observing paused state, without retrying input or resuming itself.

Actions → **Resume pane Agent control** changes the task to `ready` and invalidates the old token. The same Agent connection must observe again and acquire a fresh token. No input or model continuation is automatically started. **End pane Agent control task** revokes the record and token; the terminal program continues. Both actions can be assigned in Settings → Keybindings and have no default shortcut. The full shared PAUSED top row is a subsequent UI increment.

## Runtime scope

Ownership is shared across local processes/clients of the same managed Tmux socket. State and revocation markers are under `${XDG_RUNTIME_DIR:-/tmp/cosmos-UID}/cosmos-agent-control/`; directories are mode 0700, files 0600. File locking serializes validation/dispatch against cancellation, and atomic state replacement prevents partial JSON. State contains task labels and tokens, not screen text or API credentials. It is local runtime state, not the planned persistent scheduler.

Abandoned task records fail closed; the user can end them via Actions. There is no automatic expiry or reconnect-to-owner protocol yet. A Tmux server/layout change rejects the old token; it does not silently retarget a replacement pane. Read-only observation remains available except on private panes.

Legacy `send_text`/`send_keys`/`mouse` still work for panes without a control task. When a task exists (including paused/ready), legacy input rejects it; an Agent cannot bypass a revoked token using these tools. Same-user shell programs or raw Tmux commands are outside this trusted-tool policy, which is not an OS sandbox. The Agent prompt forbids bypassing these boundaries.

Implementation boundaries: `control.py` owns shared ownership/revocation state; `control_tools.py` adapts lifecycle and token validation to terminal tools. Input and pointer routers only report human intervention, using the existing terminal delivery and notification systems.
