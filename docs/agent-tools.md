# Cosmos Agent tools and permissions

The bundled/source Cosmos Agent advertises nine short tools. The native MCP producer maps them to existing workspace APIs, checks the canonical leaf permissions, signs conversation identity and sanitizes results. There is no second executable tool registry. Plain system OpenCode is launched unchanged and does not receive these tools.

## Tools

- `cosmos_context(target?, client?)`: current target, view, live client selection/candidates, this conversation's unfinished tasks, ownership state, paused flag, `allowed_next` and recent output. `target` accepts `%pane` or displayed `session:pane`. The first default target is the launch source; otherwise the selected client's active pane can supply it. It never lists the Actions catalog.
- `cosmos_observe(target?, layers?, region?, observation?)`: fresh positioned text/presentation/inferred-control evidence. Optional `observation` is a prior short handle for unchanged detection. Styled characters are not image pixels or Reader overlay semantics.
- `cosmos_step(target?, text?, submit?, keys?, mouse?, observation?, wait_ms?, full?)`: literal single-line paste and optional Enter, or ordered keys, or a mouse event. Use exactly one input form. Mouse requires a fresh observation handle and one-based content-cell coordinates. The adapter supplies the held pane token. Backend checks revocation before each stage. Partial delivery lists delivered stages, which must not be blindly repeated. `full=true` requests the full post-paste observation; keys/mouse return updated context and bounded recent evidence, with full inspection available through `cosmos_observe`.
- `cosmos_task(operation, ...)`: `begin` takes target, observation and task label; `release` ends own input control; `list` returns current conversation tasks; `resume` takes a task handle and reason; `finish` takes handle, outcome and evidence summary; `schedule` takes target, goal, schedule and mode; `history` takes handle. A resumed task still needs fresh observation and input approval.
- `cosmos_workspace(operation, ...)`: `list`, `begin(task)`, `release`, `terminal(target)`, `session(target,name)`, `rename(target,name)`, `focus(target,client?)`, `export(session,output?)`. A workspace grant covers creation/rename/focus only. Terminal input, close, interruption, privacy and unrelated Actions remain excluded. Creation returns actual startup/cwd data and a reusable observation.
- `cosmos_open(path,target,client?)`: routes a file/directory through Reader/Files. A pending request is not proof of loading.
- `cosmos_history(target?,query?,limit?,cursor?)`: bounded immutable scrollback pages; follow `next_cursor` for older retained rows. Privacy is checked on every page.
- `cosmos_actions(operation, ...)`: `discover(scope?,category?,client?)`, `invoke(id,scope,params?,client?)`, `events(request_id,client?,wait_ms?)`. Reader lifecycle events are emitted by the Reader itself. A routed action is not proof that a modal completed.
- `cosmos_watch(operation, ...)`: `begin(target,condition,text?,timeout_seconds?)`, `list`, `cancel(handle)` where handle is the returned watch ID. Background waiting releases held input control. Conditions/timers never resume a manually paused task.

The advertised schemas are authoritative for optional arguments. Old internal MCP methods remain available to the transport for compatibility, but are not duplicate model catalog entries.

## Results and internal handles

`cosmos_context` returns a compact context directly. Other operations return `{result, context}` with a refreshed context after execution, including structured recoverable errors. If the context transport is unavailable, the operation's result is retained and context explicitly reports unavailable; do not repeat a potentially completed mutation. A context read permission is checked before these operations, so an explicit denial cannot be bypassed by obtaining the same data as a sidecar.

Context lists at most eight unfinished tasks, with a total/truncation indicator. Recent output is at most eight nonblank rows and 1024 UTF-8 bytes, plus cursor, region, truncation and observation handle. It is terminal evidence, not a command-completion claim. Unknown targets return candidates. Disconnected/ambiguous clients return candidate IDs and never silently direct a mutation elsewhere. The task handle in the resume entry can be passed directly to `cosmos_task resume`, avoiding Actions discovery.

Model-visible observation handles (`o_...`) and task handles (`t_...`) are bound to the native conversation and Agent. The adapter retains raw snapshot identities, task revisions/challenges and control capabilities. Control/workspace tokens are absent from model schemas and results. Handle tables hold at most 128 observations/tasks per conversation/Agent; at most 128 such states are retained. Eviction/restart fails closed and requires fresh discovery. Handles are not persistent authorization and must not be copied to skills.

Manual pause invalidates backend delivery immediately. Paused context discards adapter-held pane input rights; after confirmed resume the old token is not restored. Fresh acquisition still requires a current snapshot and permission. Explicit deny policies apply to both public short aliases and canonical compatibility actions. The producer's same-conversation task grants never authorize another pane or Agent.

## Four authorization classes

Directory reads cover file reading, listing and text search under the displayed directory. Remembering a new read scope stores `cosmos_directory_read` for that project, usable by read/list/glob/grep only; it never grants Shell execution or writes. Explicit existing search-pattern denies remain honored. Conservative exact-file scopes at a relative project root remain exact-file scopes.

Terminal-task approval covers acquisition, ordinary bounded input and own release in the identified conversation/task/terminal. It expires on release, finish or manual pause and is never saved as a project wildcard. C-c/C-z/C-d and resource closing/interruption require separate one-shot confirmation even under a general allow policy.

Filesystem investigation is explicitly routed by the Agent prompt and Cosmos-only Shell tool description to native read/listing, glob and grep (with path/include/limit); changes use edit/write/patch. Shell pipelines such as `grep ... | head; echo ...; grep ...` remain Shell execution approvals even if their apparent purpose is searching. Prompt guidance is not an execution classifier or a guarantee of the model's next tool choice. When a dedicated tool cannot express an operation, the Agent must explain that limitation and request bounded Shell execution. Long approval content scrolls inside the compact card without shrinking wrapped lines; confirmation buttons remain outside the scroll area.

Host writes/execution show affected path/command and working directory where available. Mixed commands and `python -c` are execution capabilities, never read-only directory grants. New Cosmos host edit/write/patch/Shell confirmations do not save permanent wildcard approvals. Existing remembered rules remain effective until explicitly revoked; this is not an OS sandbox.

Workspace management covers creation, rename and focus, with its own task capability; it excludes close, input, interruption, privacy and unrelated Actions. Other actions retain individual permission checks. Every confirmation presentation states category, scope, lifetime and write effect. Manual task resumption is a separate blue/info card, defaults to Keep paused and cannot be remembered.

## Inspect and revoke saved rules

Open Agent Settings → Permissions, Ctrl+P → Cosmos permissions, or `/permissions`. The dialog lists the current project's saved approvals grouped by capability, including legacy Shell/action wildcard rules. Opening or inspecting does not change any rule. Selecting a rule shows its scope, lifetime and write impact; Keep approval is the default. Revoke re-fetches and verifies the exact selected ID/action/resource before deleting that one rule through OpenCode's existing saved-permission API. There is no bulk migration or automatic cleanup.

Revocation affects subsequent evaluations; it does not undo filesystem changes, kill running commands, or terminate an already-held transient task capability. Use COSMOS → Agent tasks to pause/finish those tasks. Configured allow/deny policies remain in the Agent config and are not silently rewritten by this dialog.

## Validation

The tracked native tests cover actual Tool registry short-name execution, permission checks, conversation/Agent/pane handle boundaries, resume signing, shared directory approval and revocation, and real TUI inspection/Keep/explicit single-rule deletion. Python tests cover context selection, bounded summary, privacy and stale-client recovery. No test requires a paid provider or modifies live user grants/tasks. Native changes are maintained as tracked producer helpers and reproducible patches under `integrations/opencode/`, applied by `dev/prepare_agent.py`.
