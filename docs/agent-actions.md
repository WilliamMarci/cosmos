# Cosmos Actions for Agent

Cosmos Agent includes a second local MCP server, `cosmos_actions`. It exposes the existing Action registries and routes UI operations through the same `NavigationController.execute_entry` dispatcher used by the action drawer. It does not maintain a separate list of keyboard shortcuts or reimplement the feature handlers.

## Tools

`list_actions(client?, scope?, category?)` returns:

- `service_actions`: current coordinator `actions.list` entries, including registered Mod actions. Each entry has `scope="service"`; menu entries additionally have `requires_ui=true`.
- `clients`: connected Cosmos UI client IDs discovered in this Agent's Tmux service.
- `ui`: the selected client's current `context`, `active_pane` and Action IDs/labels. This is populated automatically when there is exactly one client; with several clients, pass an explicit client to inspect one.

`invoke_action(id, scope, client?, params?)` takes the exact ID returned by discovery. `scope` must be `service` or `ui`:

- Service actions call the existing coordinator `actions.invoke` RPC, after checking the ID still exists. `params` is forwarded unchanged; an explicitly selected client is validated and added for Mod presentation. A service menu action is instead opened on a selected UI client using the existing settings-menu dispatcher.
- UI actions require a live client and an ID available in its current keymap context. They operate on that client's current pane and modal view. They currently accept no additional parameters. For example, call `workspace.focus_left` before listing the new pane's context if needed. To enter text in an application, use the terminal tools; Action invocation is not a text-input API.
- When multiple clients are attached, a UI operation requires an explicit `client`. It never silently chooses the most recent client. Unknown/disconnected clients and unavailable Action IDs return a tool error.

Example sequence:

```json
{"client":"textual-12345"}
```

Pass that to `list_actions`, then invoke a discovered UI entry:

```json
{"id":"workspace.palette","scope":"ui","client":"textual-12345"}
```

A response with `status="dispatched"` acknowledges routing only. A dialog may still need user input, and asynchronous feature work may still be running. Refresh the action list/context and verify the relevant result rather than assuming the task completed. Actions such as detach/quit can disconnect the client before an acknowledgement arrives; a transport error after those actions does not prove no effect occurred.

## Client transport and lifecycle

The existing private UI bridge also accepts `type="cosmos.actions"` requests from the same Unix UID. Requests specify a client plus `operation="list"`, `"invoke"`, `"menu"`, `"context"`, `"open_file"` or `"focus"`; focus includes a stable `pane` and reuses Switch target selection. Invocation includes an Action `id`. Responses are one newline-delimited JSON object, with an `error` field on failure. The socket is mode 0600.

Each connected UI publishes its private socket path in its Tmux service under `@cosmos_agent_actions_<client>`. Graceful shutdown removes the entry. Discovery ignores missing socket paths. A stale/unreachable entry returns an explicit connection error; the bridge does not retarget another client. A newly attached UI publishes a new client entry, so a retained Agent can refresh discovery after reconnection.

Service actions can operate without a UI when the underlying registered action supports it. Menu and client-context operations require a connected UI. Mod registration, execution permissions and notification policies remain owned by Cosmos; the Agent does not bypass them.

## Permissions and validation

OpenCode permission defaults allow `cosmos_actions_list_actions` and ask for `cosmos_actions_invoke_action`. Terminal input remains a separate permission namespace. An Action denial is not permission to synthesize equivalent keystrokes or shell calls.

`dev/test_agent_actions.py` exercises real Unix-socket requests against a running Cosmos test UI: discovery, opening settings, opening a registered service menu, rejecting stale-context actions, service RPC forwarding and requiring explicit selection for multiple clients. Coordinator calls use an isolated fixture, so the checks do not mutate a user's live settings. Existing navigation tests cover the shared dispatcher after extraction.


### Compact discovery and file routing

`cosmos_terminal.resolve_target(target)` accepts `%ID` or `session:pane`, such as
`1:4` (stable session `$1`, pane `%4`, not pane index). It returns IDs, cwd,
program and dimensions without terminal text. Private panes are denied.
`list_panes` includes `display_id`.

`cosmos_actions.list_clients()` returns only connected client IDs.
`client_context(client?)` returns client, UI context and active pane without actions.
`list_actions(client?, scope?, category?)` can restrict scope to `ui` or `service`
and filter by action ID prefix. Focus results include the resulting UI context.

`open_file(path, target, client?)` resolves the target, checks the path against
Reader/Files formats, selects that pane and uses the Reader controller to open it.
Supported Reader files are PNG, JPEG, WebP, PDF, EPUB, Markdown and HTML; this is
the Agent path for documents and images, not terminal rendering. Relative paths
resolve against target cwd. Directories open Files. Unsupported formats fail
instead of launching a desktop application. Multiple clients require
explicit selection. The result contains actual pane, display ID, path and view
kind and `request_id`, with `loading: pending` and `complete: false`: it acknowledges routing,
not successful decoding. `reader_events(request_id, client?, wait_ms=0)` returns actual
internal Reader lifecycle events, including success/failure; see [Reader events](reader-events.md). This operation can move focus and remains permission-gated.

Terminal task permissions are grouped in the patched runtime; see
[Agent control](agent-control.md). These Action APIs retain their existing
permissions and do not inherit terminal-input authority.
