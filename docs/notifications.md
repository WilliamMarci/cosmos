# Notifications

Notifications are explicit events. Normal rendering/state refresh does not create a notification. User-operation failures use error notifications; assistant integration warnings use warning; terminal BEL uses info.

## Presentation

The global stack sits at the lower right above the status bar. All cards have one fixed width based on the current client's active pane: min(pane width, 60 columns, viewport width), with a two-column minimum. Short messages keep the same width. New messages enter at the bottom and push older messages up. Expiration or dismissal removes an entry; the remaining entries close the gap. If the stack exceeds the screen, only the newest entries that fit are drawn; Leader N can access every active entry.

Repeated active, unresolved, unclaimed notices with identical text, source, level, session, actions, actionable flag and persistent/timed lifetime class merge under the same ID. The service increments `count` (initially 1), refreshes the deadline from the latest publication, clears client dismissals and moves the notice to the bottom. Expired/resolved notices start a new count. Different sessions never merge. A count above 1 appears after the content as an amber `×N`, reserved even when the message is truncated. Publication returns `{id,count}`; older persisted records without count load as 1.

Each card is one row by default. Long text wraps to at most two rows and truncates the remainder with an ellipsis. The colored left marker is the right-half block `▐`; content follows, with compact three-column action buttons at the right of the last row. Notifications do not take focus. Colors are info blue, success green, warning amber, error red, progress cyan.

Session-specific messages prefix their content with the stable Tmux session ID as superscript digits: `$1` displays `¹`, `$12` displays `¹²`. Global messages omit this tag. The tag identifies the origin; it does not filter delivery. All clients of the service receive the same notifications, subject to local dismissal and the service display setting.

Settings → Notifications has an enable switch and the default timeout. Disabling display does not delete history or stop deadlines. The default is 5000 ms. Timers belong to individual notices and are computed by the coordinator; reopening/repainting does not restart them.

## Public RPC and SDK

`notifications.publish` accepts:

- `text`: non-empty, at most 4096 bytes; control characters/newlines are rejected. The UI wraps text.
- `source`: optional source string, default core, at most 128 bytes.
- `level`: info (default), success, warning, error or progress.
- `session_id`: optional stable Tmux `$N` ID; a non-negative integer or numeric string is also accepted and normalized to `$N`. Omit it for a global notification.
- `ttl_ms`: omitted/null uses the configured default for ordinary notices. A positive value is clamped to 100 ms–24 hours. `0` keeps the notification indefinitely.
- `persistent`: true also prevents expiration.
- `actions`: up to three `{id,label}` objects. IDs are unique within the notice, at most 64 bytes. Labels are at most 64 bytes, drawn in three character cells.
- `actionable`: compatibility flag. Actions automatically make a notice actionable. Actionable notices remain indefinitely unless a positive ttl_ms is explicitly supplied.

```python
api.notify("Build failed", level="error", session_id="$1")
api.notify("Background task started", level="progress", ttl_ms=3000)
api.notify("Continue?", level="warning", session_id="$1", ttl_ms=0,
           actions=[{"id": "yes", "label": "yes"}, {"id": "no", "label": "no"}])
```

The SDK signature preserves positional `text, actionable=False, actions=None` and adds keyword-only `level="info", ttl_ms=None, persistent=False, session_id=None`. The in-process `app.notification_events.publish` accepts the same metadata with keyword source/actions and defaults its session ID to the client's current session.

The resulting Notice includes id, text, count, source, level, session_id, created_ms, expires_ms, actionable, resolved, actions, selected_action and client dismissal/claim state. `expires_ms=null` means no deadline. Older persisted notices without level/session metadata load as info/global.

`notifications.active {client}` returns unresolved, unexpired, locally visible entries; `notifications.list {client}` includes retained history. Both preserve publication order. `notifications.dismiss {id,client}` hides only for that client. `notifications.act {id,action,client}` resolves the declared action service-wide; other clients remove it. Expired/already resolved/claimed actions cannot be selected. Publishers consume notifications.action events to perform their own operation. No action is evaluated as a shell command by the notification service. Existing claim/complete/release/resolve operations remain available.

## Terminal bell

The dedicated Cosmos Tmux server installs one stable `alert-bell[900]` hook, with monitor-bell on and bell-action any. Reconnecting clients replace the same slot; they do not add one publisher per client. A BEL in any monitored session publishes an info notification with its hook_session and window ID. The hook uses the current coordinator path and environment, including private XDG paths, and does not start a coordinator if it is stopped. Hook subprocess output is suppressed. The hook persists with retained Tmux applications; reconnect installs the current package's hook.

The coordinator must be restarted after upgrading from a version without severity/session/lifetime fields to use the full contract. `cosmos stop` retains Tmux applications and stops coordinator-managed Mods; reopen Cosmos afterward.
