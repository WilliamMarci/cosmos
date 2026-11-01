# Pane input ownership

The default native model catalog now uses the [short Cosmos Agent interface](agent-tools.md). Names such as `acquire_control` below document the internal MCP compatibility contract; tokens and resume credentials are held by the native adapter and are not model-facing arguments.

This increment implements cross-process input ownership and user revocation. The shared Taking over/PAUSED top row is implemented. A distinct cyan mouse pointer and background terminal watches are implemented. Native model cancellation and persistent task wakeups are implemented; see [Agent tasks](agent-tasks.md).

## Tools

- `authorize_control(pane, operations, seconds=600)` returns a bounded allowance after one explicit user approval. The adapter stores it for the conversation/agent/pane and uses it only to skip later control-acquisition prompts until expiry; manual pause/end or expiry revokes it. It does not acquire input, create a task or grant Shell/Actions.
- `control_status()` returns controlled panes, task labels and states (`active`, `paused`, `ready`), without ownership tokens.
- `acquire_control(pane, snapshot_id, label, takeover=False)` requires a snapshot observed by the same authenticated runtime conversation, re-observes the same region, and rejects changed snapshots. It returns a cryptographically random token and a fresh control lease ID; it does not create a persistent task. Another active owner cannot replace it. A paused lease can be taken over only with `takeover=true` through the user-approved `cosmos_control begin`; that approval is the takeover confirmation, and an allowance cannot bypass it.
- `control_input(pane, token, kind, arguments, snapshot_id=None)` accepts `send_text`, `send_keys` or `mouse` using the existing terminal input argument names. Tokens belong to one authenticated conversation, control lease and stable pane; they are separate from persistent task rows. Mouse requires a fresh observation ID covering its target cell. Tmux server PID and pane window identity are checked for text/keys; mouse additionally validates dimensions and revalidates its observation. A harmless resize does not invalidate text/keys. These are sampled checks, not atomic application transactions.
- `release_control(pane, token)` ends the owner's control lease, including one paused with that token. `end_control(pane)` clears this conversation's own or legacy lease without a token. Neither sends Ctrl+C, closes a pane or stops a terminal program.

The patched runtime groups control acquisition, ordinary controlled input and own release/end under one scoped confirmation, as described below. Other mutations retain their native permission checks. Ownership alone does not grant unrelated permissions. `control_input` returns `delivery=delivered`, `action_complete=false`, `task_complete=false`: downstream evidence is still required.

## Human input and recovery

A key actually delivered to a terminal pane, pasted text or a forwarded mouse event pauses that pane's control lease before normal UI/terminal handling. Changing focus or sessions, opening Cosmos menus and other UI actions do not pause control. Mouse forwarding (including wheel and drag) also revokes ownership. This applies when keyboard passthrough is enabled. The first transition emits a notification; repeated input does not repeat it. Control pauses do not create or modify persistent task rows; task-level human-input pauses remain a separate Tasks policy.

A pause marker is published before waiting for an in-flight sender's lock. Controlled input checks it immediately before dispatch; queued/stale tokens fail. Input already dispatched cannot be recalled. This is not a hard real-time guarantee and aborts a native Cosmos Agent model turn through its Session API. Plain system OpenCode has no such integration. The Agent prompt requires returning to the user after observing paused state, without retrying input or resuming itself.

For an explicit continuation request, the Agent can offer a one-time [resume confirmation](agent-tasks.md#agent-requested-resume-confirmation); the same approval resumes the persistent task and authorizes one fresh takeover. The old token is never reused. Actions → **Resume pane Agent control** changes a control-only lease to `ready`; the next `cosmos_control begin` is the takeover approval. **End pane Agent control** revokes the record and token; the terminal program continues. Both actions can be assigned in Settings → Keybindings and have no default shortcut. The shared PAUSED top row remains reserved while a control lease or persistent task header targets the pane.

## Runtime scope

Ownership is shared across local processes/clients of the same managed Tmux socket. State and revocation markers are under `${XDG_RUNTIME_DIR:-/tmp/cosmos-UID}/cosmos-agent-control/`; directories are mode 0700, files 0600. File locking serializes validation/dispatch against cancellation, and atomic state replacement prevents partial JSON. State contains task labels and tokens, not screen text or API credentials. It is local runtime state, separate from the persistent scheduler.

Abandoned task records fail closed; the user can end them via Actions. There is no automatic expiry or reconnect-to-owner protocol yet. A Tmux server/layout change rejects the old token; it does not silently retarget a replacement pane. Read-only observation remains available except on private panes.

Legacy `send_text`/`send_keys`/`mouse` still work for panes without a control lease. When a control lease exists (including paused/ready), legacy input rejects it; an Agent cannot bypass a revoked token using these tools. Same-user shell programs or raw Tmux commands are outside this trusted-tool policy, which is not an OS sandbox. The Agent prompt forbids bypassing these boundaries.

Implementation boundaries: `control.py` owns shared ownership/revocation state; `control_tools.py` adapts control leases and token validation to terminal tools without creating Tasks rows. Input and pointer routers only report human intervention, using the existing terminal delivery and notification systems.

## Shared takeover header

An active temporary control lease or persistent task displays `COSMOS Taking over`, a locally animated braille indicator and its label/goal. Label and activity use adjacent background blocks, without a literal separator character. Busy feedback runs at 8 frames/second normally and 2 frames/second under reduced motion; the independent pointer remains steady under reduced motion. A manually paused control or paused/blocked task displays static `COSMOS PAUSED` with a monochrome `⏸︎`; `ready` adds a reminder that fresh observation is required. Control takes precedence when both records target the same pane. The same pane status is visible in every connected Cosmos client. Clicking the header pauses control without forwarding a mouse event into the application. Text is drawn by the existing `TerminalSurface`, never written into shell history.

Reservation uses Tmux's native window-level `pane-border-status=top`. While any controlled or task-owned pane remains in a window, all its panes therefore have native top-border positions, but only control/task panes show takeover text. This backend granularity is intentional: actual PTY dimensions, captured grids, application cursor and input coordinates remain consistent across clients. The prior local option (or inherited setting) is restored when the last control lease ends; pause/resume does not resize. A `@cosmos_control_header` window option records restoration metadata, not tokens.

Acquisition re-observes after reservation and returns the resulting `snapshot_id` and `dimensions`; geometry validation uses the resized application area. Tools remain one-based application-content cells, excluding the header. The UI reconciles shared state and layout, refreshing active header rows for animation; paused rows do not animate. UI detach keeps reservations/tasks intact. End/release restores layout when no task header still targets the pane; there is still no automatic orphan control expiry. Logical task continuation uses the scheduler. `headers.py` handles native reservation, and `header_ui.py` handles character composition.

## Agent pointer

After successful controlled mouse input, all Cosmos clients display a cyan diamond at the one-based application-content cell, independently of the application cursor. It blinks through the existing terminal renderer; reduced motion leaves it steady. Pausing control, releasing it, changing the geometry or sending non-mouse controlled input removes the pointer. Header and pointer animation refresh only their affected rows/cells. The pointer is character chrome, not an image-pixel inspection facility.

For background waits, [terminal watches](agent-monitor.md) can release the owner's control token/header and collect evidence independently; native authenticated watches can wake the saved conversation through the scheduler.


### Bounded terminal step

`terminal_step(pane, token, text="", submit=false, wait_ms=100, full=false)` pastes one literal
single line, optionally sends Enter, then returns a compact initial snapshot or positioned changed rows.
Omitting text/submit is a wait-only observation. The wait is bounded to 0–2000 ms.
A Tmux copy/view mode is cleared before input and reported as `mode_cleared`;
observations expose `pane_in_mode` and the visible screen mode. Each input uses
its own ownership/revocation check so manual input can stop submission after
paste. Newlines and NUL are rejected before any delivery. On failure after
delivery, the response reports `delivery: partial` and the delivered stages;
never blindly repeat that input.
Successful delivery still sets `action_complete` and `task_complete` to false.
In the patched runtime this tool uses the acquired task capability; plain system OpenCode has no Cosmos tools.


## Conversation/control/pane permission scope

Cosmos's patched OpenCode adapter asks once at `acquire_control` for a named
temporary control lease, unless an unexpired explicit `authorize_control`
allowance covers the same conversation/agent/pane. The permission resource
contains the native model conversation ID, stable pane ID, display label and a
unique acquisition identity.
After successful acquisition, the returned token and `task_id` identify the
adapter grant; they do not identify a persistent Tasks row. Ordinary
`control_input` and `terminal_step` reuse the grant. `release_control` or
`end_control` ends only the conversation's own control and does not ask again,
including after manual pause.
Explicit configured denies and permission hooks still apply. Control-key input
containing Ctrl+C, Ctrl+Z or Ctrl+D keeps a separate transient confirmation;
workspace management has its own explicit task capability below; other Actions keep their existing permissions.

These task checks ignore project-saved approvals, including old wildcard rules.
Requests carry `save: []`; choosing Always has only one-request effect and cannot
persist this task permission. Grants live only in the patched Agent process,
never in the project permission database. A successful new acquisition rotates
the pane grant. Input failures, partial delivery, pause/control loss and release discard it; a pre-input validation error or wait-only step does not. Process
restart loses the grant and fails closed; orphan control records still need the
existing user recovery Actions. A configured explicit allow can still customize
the default confirmation policy.

The adapter supplies an authenticated conversation envelope derived from the
native tool execution context, overwriting model-supplied identity. The per-launch
HMAC key is passed only in process environment, not model configuration or tool
schemas. Python keeps separate observation caches, ownership identity and token
geometry per authenticated conversation, even when the MCP process is shared.
A different conversation cannot use another conversation's snapshot or release
its task. The signature prevents the model choosing an arbitrary conversation
through tool arguments; it is not protection against trusted same-UID programs
reading process secrets, and is not an OS sandbox.

Manual pause revokes input at the backend before delivery; an adapter grant cannot
override it. Resume invalidates the old token. Fresh observation and acquisition
then require a new task confirmation under default policy. The persisted task pause also cancels the native model turn.

Plain system OpenCode is launched without a Cosmos profile, tools or skills;
these APIs and grants apply only to Cosmos Agent.
Restart the Agent frontend after updating this patch. Ordinary Cosmos clients and
retained terminal applications do not need to be stopped.

Implementation: `integrations/opencode/task-permissions.patch` patches MCP and
permission evaluation; `cosmos-permissions.ts` holds transient grants;
`conversation.py` authenticates context and partitions the Python tool state.
`dev/prepare_agent.py` installs the tracked integration idempotently.


## Workspace-management task

`acquire_workspace(task)` confirms one named task for this authenticated
conversation and Cosmos Tmux service. It returns `token`, `task_id`, `task`,
`state: active`, `scope: workspace`, and the exact capability list:
`create_terminal`, `create_session`, `rename_target`, `focus_pane`. Pass the token
as optional `workspace_token` to those tools. Without it they retain independent
native tool permission checks. `release_workspace(token)` ends only the owner's
grant, without another confirmation or any terminal changes.

This scope intentionally covers workspace management across sessions in the
service, rather than permission to type in any pane. It does not cover closing,
interrupting, changing privacy, exporting files, opening Reader, invoking other
Actions or terminal input. It cannot be substituted for a pane control token.
The same explicit-deny rules, signed conversation identity and nonpersistent
permission behavior apply. A new workspace acquisition rotates the conversation's
previous workspace token; release/restart/management-tool errors invalidate reuse.
Workspace grants are independent of the persistent task scheduler and never grant terminal input.


## Compact context and lifecycle outcomes

`cosmos_terminal.context(target?, client?)` combines target metadata, connected client IDs, current UI context (when a client is unambiguous), this authenticated conversation's unfinished tasks and current control status. `target` accepts `%pane` or the displayed `session:pane`. It does not enumerate Actions or return terminal history. Unknown targets return candidates, ambiguous/stale clients return connected IDs, and paused tasks include the current `resume_challenge`. It does not resume a task or grant input permission.

Acquisition synchronizes the pane header and takes a fresh observation; it never creates or reuses a persistent task. Control leases and task rows have independent lifetimes. Ownership conflicts and pauses return an MCP error whose text is JSON with `status`, `message` and `next`; ordinary validation failures remain errors. A conflict does not require the model to mark housekeeping tasks failed.

A successful release is remembered for the last 128 handles in that tool connection. Closing the same handle again returns `state: ended, already_finished: true`; it never releases a replacement lease. Unknown handles and handles from other connections remain invalid. Receipts are transient and disappear on restart.

Step observations use `mode: snapshot`, `delta` or `full`. Deltas identify `base_snapshot_id`, contain positioned changed nonblank `text` rows, and list blank/removed row numbers in `cleared_rows`. Apply row replacements, not append operations. Layout/program changes reset to a compact snapshot. Compact text is limited to 24 nonblank rows and 4096 UTF-8 bytes; `truncated` requires a full observation if omitted content matters. A truncated delivery cannot become a complete delta baseline. `full=true` explicitly returns the original full observation. Per-connection comparison state is bounded to 32 panes; it is not durable history.
