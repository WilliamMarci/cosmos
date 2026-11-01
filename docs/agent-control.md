# Pane input ownership

This increment implements cross-process input ownership and user revocation. The shared Taking over/PAUSED top row is implemented. A distinct cyan mouse pointer and background terminal watches are implemented. Native model cancellation and persistent task wakeups are implemented; see [Agent tasks](agent-tasks.md).

## Tools

- `control_status()` returns controlled panes, task labels and states (`active`, `paused`, `ready`), without ownership tokens.
- `acquire_control(pane, snapshot_id, task)` requires a snapshot observed by the same authenticated runtime conversation, re-observes the same region, and rejects changed snapshots. It returns a cryptographically random token and a fresh `task_id`. Another owner cannot replace it, and a manually paused task cannot reacquire until a user resumes it.
- `control_input(pane, token, kind, arguments, snapshot_id=None)` accepts `send_text`, `send_keys` or `mouse` using the existing terminal input argument names. Tokens belong to one authenticated conversation, task and stable pane. Mouse requires a fresh observation ID covering its target cell. Tmux server PID, pane window and dimensions are checked against acquisition; layout changes require a fresh acquisition. Mouse additionally revalidates its observation before input. These are sampled checks, not atomic application transactions.
- `release_control(pane, token)` ends the owner's task, including one paused with that token. It does not send Ctrl+C, close a pane or stop a terminal program.

The patched runtime groups task acquisition, ordinary controlled input and own release under one scoped confirmation, as described below. Other mutations retain their native permission checks. Ownership alone does not grant unrelated permissions. `control_input` returns `delivery=delivered`, `action_complete=false`, `task_complete=false`: downstream evidence is still required.

## Human input and recovery

A physical non-modifier key in a workspace terminal, pasted text or a click on a terminal pane pauses that pane's control task before normal UI/terminal handling. Mouse forwarding (including wheel and drag) also revokes ownership. This applies when keyboard passthrough is enabled. The first transition emits a notification; repeated input does not repeat it.

A pause marker is published before waiting for an in-flight sender's lock. Controlled input checks it immediately before dispatch; queued/stale tokens fail. Input already dispatched cannot be recalled. This is not a hard real-time guarantee and aborts a native Cosmos Agent model turn through its Session API. Plain system OpenCode has no such integration. The Agent prompt requires returning to the user after observing paused state, without retrying input or resuming itself.

Actions → **Resume pane Agent control** changes the task to `ready` and invalidates the old token. The same Agent connection must observe again and acquire a fresh token. For native logical tasks, resuming queues a fresh model inspection; it does not restore input ownership. **End pane Agent control task** revokes the record and token; the terminal program continues. Both actions can be assigned in Settings → Keybindings and have no default shortcut. The shared PAUSED top row remains reserved until the control task ends.

## Runtime scope

Ownership is shared across local processes/clients of the same managed Tmux socket. State and revocation markers are under `${XDG_RUNTIME_DIR:-/tmp/cosmos-UID}/cosmos-agent-control/`; directories are mode 0700, files 0600. File locking serializes validation/dispatch against cancellation, and atomic state replacement prevents partial JSON. State contains task labels and tokens, not screen text or API credentials. It is local runtime state, separate from the persistent scheduler.

Abandoned task records fail closed; the user can end them via Actions. There is no automatic expiry or reconnect-to-owner protocol yet. A Tmux server/layout change rejects the old token; it does not silently retarget a replacement pane. Read-only observation remains available except on private panes.

Legacy `send_text`/`send_keys`/`mouse` still work for panes without a control task. When a task exists (including paused/ready), legacy input rejects it; an Agent cannot bypass a revoked token using these tools. Same-user shell programs or raw Tmux commands are outside this trusted-tool policy, which is not an OS sandbox. The Agent prompt forbids bypassing these boundaries.

Implementation boundaries: `control.py` owns shared ownership/revocation state; `control_tools.py` adapts lifecycle and token validation to terminal tools. Input and pointer routers only report human intervention, using the existing terminal delivery and notification systems.

## Shared takeover header

An active task displays `COSMOS Taking over`, a locally animated braille indicator and its task label. A manually paused task displays static `COSMOS PAUSED │ ⏸︎`; `ready` adds a reminder that fresh observation is required. The same pane status is visible in every connected Cosmos client. Clicking the header pauses control without forwarding a mouse event into the application. Text is drawn by the existing `TerminalSurface`, never written into shell history.

Reservation uses Tmux's native window-level `pane-border-status=top`. While any controlled pane remains in a window, all its panes therefore have native top-border positions, but only controlled panes show takeover text. This backend granularity is intentional: actual PTY dimensions, captured grids, application cursor and input coordinates remain consistent across clients. The prior local option (or inherited setting) is restored when the last control task ends; pause/resume does not resize. A `@cosmos_control_header` window option records restoration metadata, not tokens.

Acquisition re-observes after reservation and returns the resulting `snapshot_id` and `dimensions`; geometry validation uses the resized application area. Tools remain one-based application-content cells, excluding the header. The UI reconciles shared state and layout, refreshing active header rows for animation; paused rows do not animate. UI detach keeps reservations/tasks intact. End/release restores layout; there is still no automatic orphan ownership expiry. Logical task continuation uses the scheduler. `headers.py` handles native reservation, and `header_ui.py` handles character composition.

## Agent pointer

After successful controlled mouse input, all Cosmos clients display a cyan diamond at the one-based application-content cell, independently of the application cursor. It blinks through the existing terminal renderer; reduced motion leaves it steady. Pausing control, releasing it, changing the geometry or sending non-mouse controlled input removes the pointer. Header and pointer animation refresh only their affected rows/cells. The pointer is character chrome, not an image-pixel inspection facility.

For background waits, [terminal watches](agent-monitor.md) can release the owner's control token/header and collect evidence independently; native authenticated watches can wake the saved conversation through the scheduler.


### Bounded terminal step

`terminal_step(pane, token, text, submit=false, wait_ms=100)` pastes one literal
single line, optionally sends Enter, then returns a fresh text observation.
The wait is bounded to 0–2000 ms. Each input uses its own ownership/revocation
check so manual input can stop submission after paste. Newlines and NUL are
rejected before any delivery. On failure after delivery, the response reports
`delivery: partial` and the delivered stages; never blindly repeat that input.
Successful delivery still sets `action_complete` and `task_complete` to false.
In the patched runtime this tool uses the acquired task capability; plain system OpenCode has no Cosmos tools.


## Conversation/task/pane permission scope

Cosmos's patched OpenCode adapter asks once at `acquire_control` for a named
terminal task. The permission resource contains the native model conversation ID,
stable pane ID, task label and a unique acquisition identity. After successful
acquisition, the returned token and `task_id` identify the grant. Ordinary
`control_input` and `terminal_step` reuse it. `release_control` ends only the
conversation's own token and does not ask again, including after manual pause.
Explicit configured denies and permission hooks still apply. Control-key input
containing Ctrl+C, Ctrl+Z or Ctrl+D keeps a separate transient confirmation;
workspace management has its own explicit task capability below; other Actions keep their existing permissions.

These task checks ignore project-saved approvals, including old wildcard rules.
Requests carry `save: []`; choosing Always has only one-request effect and cannot
persist this task permission. Grants live only in the patched Agent process,
never in the project permission database. A successful new acquisition rotates
the pane grant. Input failures, partial delivery and release discard it. Process
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
