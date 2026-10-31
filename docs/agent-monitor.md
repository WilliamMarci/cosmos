# Terminal watch service

This increment supplies an independent deterministic terminal monitor. It makes no provider/model requests and does not grant input ownership. Automatic model wakeup, native task/sidebar management, Bash-ready adapters and scheduled/recurring Agent tasks are not yet implemented.

## Tools

- `watch_terminal(pane, condition, text="", timeout_seconds=300, control_token=None)` registers a watch and returns immediately. Conditions: `text_present`, `text_absent`, `changed`, `program_changed`. Text predicates use literal, case-sensitive substrings (maximum 256 characters), never regular expressions. Timeouts range from 1 second to 24 hours. At most 32 watches may wait in one managed Tmux service.
- If `control_token` is supplied, the owner releases control/header reservation before establishing the baseline. Registration failure does not reacquire ownership. A later continuation must observe and acquire a new token. Without a token, monitoring itself does not release someone else's control task.
- `terminal_watches()` returns bounded watch states and compact results, without baseline hashes or literal search needles. It is read-only and allowed by default.
- `cancel_terminal_watch(id)` cancels detection without interrupting the terminal program. Cancelling an already finished watch returns `cancelled=false`; it does not overwrite evidence.

Watch states: `waiting`, `matched`, `timed_out`, `invalidated`, `cancelled`. Results explicitly contain `task_complete=false` and `model_woken=false`. A matched condition is evidence for later verification, never proof that the user's task is complete. Registration advertises `model_wakeup_available=false`. The Agent should report the waiting watch and return; repeated model sleep/read loops are not a substitute for the future wakeup adapter.

## Detection and evidence

The detached worker polls each watched pane once per pass, sharing captures across watches of that pane. Passes are separated by 200 ms; capture load can increase latency. Captures are bounded to 64 KiB, and truncation invalidates a watch. Known Cosmos credentials are masked by the existing terminal policy. Private panes, missing targets, or changes to server PID/window/dimensions invalidate pending watches rather than retargeting another application.

Text predicates and program changes are checked on each sample. The row-difference detector coalesces changes for approximately 300 ms. It keeps at most eight recent hashes per row to identify local repeating text-frame animation as inference. Recognized repeating rows are excluded from a `changed` condition's meaningful rows; animation disappearance or a stable screen never means success. This is not a general animation classifier, native busy/input-request protocol or styled-grid monitor yet. Startup animation cycles and never-repeating progress may resemble ordinary changes.

Baselines are established before registration returns; register before sending an action if its subsequent persistent change is important. Sampling cannot guarantee capture of fleeting changes between samples or close the full action/subscription race. Native output sequencing and adapter events are required for that later reliability step. Watches currently cover the visible pane, not retained history or image pixels.

Manual control pause does not stop monitoring. Conditions may still be recorded/notified, but the worker never runs a model, sends input or resumes a pane.

## Storage and lifecycle

A single worker per managed Tmux socket uses a private SQLite database beside the control runtime files under `${XDG_RUNTIME_DIR:-/tmp/cosmos-UID}/cosmos-agent-control/`. Files are mode 0600 and directories 0700. Stored baselines contain row hashes, dimensions, process identity and program name, not complete screen transcripts. Literal configured search text is private task data. At most 512 completed records are retained, plus waiting watches; new registrations prune older completed records.

Database state survives UI/Agent detach and ordinary process/service restarts while the runtime directory remains. This is not the future durable scheduler and does not promise survival of runtime-directory cleanup/reboot. Atomic terminal-state updates prevent duplicate results. The worker-start/idle-exit handoff is serialized so new registrations cannot be stranded by an exiting idle worker; startup contenders have only one active worker. It exits when no watches remain.

Completion, invalidation and timeout use the normal notification API and notification settings. A failed notification does not discard the persisted result. Bounded rotated `.monitor.log` files contain diagnostic failures, not captured terminal text or API requests.

`cosmos stop` suspends the worker and preserves waiting records. Reopening a Cosmos UI resumes pending monitoring; registering a new watch also starts/restarts the worker. Raw coordinator shutdown RPC bypasses this CLI lifecycle step. An unexpected worker failure is logged; UI reconnect/new registration recovers pending watches, rather than a built-in crash watchdog automatically restarting it. No model or terminal input is resumed by recovery.
