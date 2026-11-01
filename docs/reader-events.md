# Reader loading lifecycle events

Reader completion is reported by internal lifecycle events, independently of
terminal capture, notification visibility or Agent rendering guesses.

`cosmos_actions.open_file(path, target, client?)` returns the selected client,
actual pane/path/view and a unique `request_id`. `loading: pending` acknowledges
routing only. The selected client's Reader registers the request on its shared
`core.events.ClientEvents` journal. `LoadingFrames` emits a terminal event only
after preparing a frame or catching the actual loading error.

Event topics are `reader.loading`, `reader.loaded`, `reader.failed` and
`reader.superseded`. Each event has `seq`, `topic`, and `data` containing
`request_id`, stable `pane`, `path`, `status` and optional `error`. Replacing or
closing a pending view emits superseded. Stale asynchronous rendering cannot
complete a newer request. Failures continue through the existing error/notification
path; disabling notifications does not disable lifecycle events.

`cosmos_actions.reader_events(request_id, client?, wait_ms=0)` consumes the last
event from that Reader request. A 0–2000 ms bounded wait can wait for the pending
request's lifecycle transition; it does not repeatedly capture the terminal or
start a model polling loop. Multiple clients require explicit selection. The
original client must remain connected; no retargeting or guessed success occurs.
Private-pane checks apply before and after waiting. Actual error text is redacted
before returning it to the Agent.

`loaded` means the initial reading frame was prepared: PDF/image rendering,
Files listing, or initial rich-document frame. It does not assert that every lazy
inline image, thumbnail or prefetch has finished. An initial failed request stays
failed if later settings changes cause a retry; reopen for a new request identity.

The journal holds 256 client-local events and the Reader retains 128 request
records. They are runtime state, not a persistent service scheduler or a coordinator
subscription. Requests expire with record eviction or UI shutdown. Events do not
automatically wake a model; that remains a separate scheduler integration.
