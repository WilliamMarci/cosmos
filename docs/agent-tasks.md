# Persistent Agent tasks

The default model-facing entry points are `cosmos_task` and `cosmos_watch`; see [Agent tools and permissions](agent-tools.md). Detailed method names below describe the internal compatibility transport, not additional model catalog entries.

Cosmos Agent supports terminal-event wakeups, one-time schedules, intervals and daily wall-clock schedules. The scheduler is a detached local Python process; model execution stays in the patched native Agent Session service. Plain system OpenCode has no task integration.

## User interface

**COSMOS → Agent tasks** or **Actions → Agent tasks** opens a compact framed popup with a transparent outside background. Tasks are shared by clients of the managed Tmux service. Select a task for its goal, state, next local time and evidence. The bottom controls apply to the selected task: pause, resume, check now and more. More contains run history, native pending permission replies (Once/Reject), auto/manual wake mode, rescheduling, cancel, and a separately confirmed **Interrupt program** action. Cancelling or pausing never sends Ctrl+C; the explicit interrupt action does.

Task actions are registered in Settings → Keybindings and contextual Actions. Defaults in the Tasks popup: `p` pause, `r` resume, `c` check, Enter options, `q`/Escape close. The popup entry has no default binding. **Settings → Agent tasks** persists concurrent primary runs (default 2), minimum wake interval (default 2000 ms), and model-run timeout (default 300 seconds).

Reschedule accepts a JSON schedule, for example `{"daily":"09:00","timezone":"Europe/Zurich"}` or `{"interval_seconds":300}`. Task creation is exposed to the authenticated Agent tools below; there is no separate visual task-authoring wizard.

## Agent tool API

- `schedule_task(pane, goal, schedule, mode="auto", control_token=None)` creates a task bound to the authenticated native conversation, stable pane and current Tmux server identity. `goal` is 1–4000 characters. `schedule` contains exactly one of `after_seconds`, `at`, `interval_seconds`, or `daily` (optional IANA `timezone` for daily). Relative/interval seconds range from 1 to 31622400; `at` is ISO 8601 with an explicit offset; `daily` is HH:MM. Mode is `auto` or `manual`. Own input ownership is released before background waiting. Returns `task`, `model_wakeup_available:true`, `task_complete:false`.
- `watch_terminal` attaches its condition/timeout to a logical task in the authenticated conversation and returns its `task_id`. Native tasks advertise automatic wakeup. Standalone unauthenticated terminal-tool callers get detection only.
- `list_tasks()` returns at most 256 task records belonging to this conversation, with active records first and without runtime authentication data.
- `task_history(id)` returns the last 32 run records for an owned task: ID, state, trigger evidence, timestamps and result summary.
- `finish_task(id, outcome, summary)` reports `succeeded`, `failed`, or `needs_input`, with a 1–2000 character evidence summary. It cannot finish another conversation's task or a paused/cancelled task. Own input leases are released. Successful recurring tasks return to waiting; other outcomes stop automatic recurrence until user intervention. Success is an Agent evidence report, not an independently proven application result.

Conversation identity is supplied by the signed native adapter, never a model argument. Scheduling keeps its native permission check. Listing/history/finish are allowed by default, subject to ownership checks. Waking never grants input ownership or approval: the continuation must observe again, acquire a fresh token and satisfy the existing scoped permission rules.

## Scheduling and restart behavior

The durable ledger lives at `~/.config/cosmos/agent/tasks/<service-hash>.sqlite3` (XDG/private Agent profile aware). `COSMOS_TASKS_HOME` overrides the directory. Directories are 0700, files 0600, owned by the current user; symlink database/profile paths are rejected. Goals, conversation IDs, target identity, schedules, compact results and run history are stored. Credentials and input tokens are not stored in this ledger. At most 128 nonterminal tasks are accepted per service.

Once/interval tasks persist their next timestamp. After downtime, an overdue once task is admitted once; missed interval/daily slots coalesce into one catch-up, then advance to the next future occurrence. Daily tasks save the creation-time host IANA timezone, unless explicitly supplied. Later host timezone changes do not rewrite it. A missing DST wall time advances to the first valid minute that day; a repeated wall time uses the first occurrence only.

UI detach and SSH disconnect do not stop the scheduler. `cosmos stop` suspends it and cancels active model turns while preserving schedules and terminal applications; reopening the UI recovers it. A replacement native headless server can reopen the persisted Agent conversation if its frontend has exited. It uses the same private profile/provider configuration and authenticated local Unix transport. Missing provider credentials or a replaced/private target block execution; a new pane is never guessed from an old ID. A lost runtime watch wakes for fresh inspection with `condition_met:false`, rather than inventing success.

Only one scheduler holds the per-service worker lock. Claims are transactional and revisions guard stale state. Each run uses a stable native message ID, so retries of an uncertain admission reuse the same message. After a model turn returns without a new watch or explicit finish, the task becomes `needs_review` (or waits for its next recurrence); model completion alone is never task success. A model-run timeout cancels the native turn and requires review.

## Pause, cancellation and permissions

Human keyboard, paste and mouse input revoke input ownership before delivery. Both active control tasks and background tasks targeting that pane are paused. A persisted conversation fence prevents automatic task wakeups and queued task model runs. Explicit new user chat is admitted separately, without clearing the task pause or granting terminal ownership. Native Session interruption aborts the running model request. Already delivered terminal input cannot be recalled; this is not a hard real-time guarantee. Monitoring can continue recording conditions while paused. Resume is a user action, invalidates the old input token and starts a new inspection. Pauses survive service restart.

Primary Agent turns are serialized by conversation and use SQLite leases across native processes, with a default limit of two per Cosmos service. Waiting for permission also holds its primary-run slot; respond in the original Agent UI or Tasks → Pending permissions. Auxiliary title/summary generation is outside this primary-turn limit. Native approval rules remain authoritative; the scheduler cannot self-approve a request.

The native bridge uses a private owned Unix socket and a per-launch authentication key. It exposes only status, wake, interrupt and explicit pending permission replies, not provider credentials. Stale process leases are reclaimed using PID plus process start identity. A fallback short private socket directory under `/tmp/cosmos-UID/` is used when an XDG path would exceed Unix socket limits. This is a trusted same-user system, not an OS sandbox.

## Limits

There is no built-in crash supervisor; UI reconnect or a new task registration recovers a failed worker. Runtime terminal watches remain sampled and can miss transient screen events; the durable ledger does not make them an output-event journal. Native Bash prompt sequence signals are available for newly sourced `cosmosrc`; arbitrary TUI input requests and file/process completion adapters are not universally detected. Tasks are managed in the Cosmos popup, not an additional native OpenCode sidebar. Image/pixel observation remains outside this task API.

## Chat while a terminal task is paused

A manual pause is an operational state, not an HTTP failure. An explicit user prompt can continue the same model conversation while its terminal task stays paused. Each such admission grants one chat-only primary turn through the normal concurrency limit; it does not restore input tokens, permission grants or task schedules. The scheduler recovery path distinguishes chat-only runs and leaves them alone. A new manual pause still cancels the active turn and clears queued chat permits. An automatic Unix wake while paused returns `accepted:false`, `paused:true`, `task_state:"paused"`, and `resume_in:"COSMOS → Agent tasks → Resume"`. Task Resume remains the explicit operational recovery path, followed by fresh observation/acquisition.

An expired Tasks permission request returns a stale result and a warning to reopen Pending permissions. If expiry races with reply, the bridge refreshes pending requests and reports stale when that request has disappeared; unrelated transport/native failures remain errors.

## Agent-requested resume confirmation

When the user explicitly asks to continue paused work, the Agent calls `list_tasks()` to get the paused task's `id`, `pane`, `revision` and opaque `resume_challenge`, then calls `request_resume(id, pane, revision, resume_challenge, reason)`. The native Agent presents a blue/information-colored **Task resume confirmation**, with **Keep paused** (default) and **Resume task**. There is no Always choice. Ordinary chat and automatic wakeups must not request it. The Tasks menu remains an alternative recovery route.

Resume always requires a fresh native user decision, even with configured or project-saved tool allows; configured denies still apply. A private signed approval binds the native conversation, task, terminal, revision, challenge and reason. It is not an argument a model can mint. Additional human input, a changed task, a replaced service, a private target, a forged decision or replay rejects the resume. A different task/conversation cannot reuse approval.

Approval resumes only the chosen task and reassigns its ready record to the authenticated current tool connection when reconnecting. It invalidates old input tokens and does not enqueue another model turn; the current explicit chat proceeds. The response is `resumed:true`, `state:ready`, `input_ownership:false`. The Agent must observe again and acquire a new token under the existing terminal task permission policy. Other paused tasks remain paused. Declining makes no task/input changes.

The native integration uses `resume-ui.patch` and `CosmosPermissions` rather than another independent UI writer. The signed approval and pause marker checks live in `features/agent/tasks/resume.py`.

Human-only Resume Actions remain available in the Cosmos UI but are excluded from the Agent action catalog. The Agent Action proxy rejects `workspace.resume_control` and `tasks.resume`; Agents must use the dedicated confirmation tool rather than bypass it through a generic Action grant.
