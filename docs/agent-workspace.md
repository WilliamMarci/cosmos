# Cosmos workspace interface

Agent workspace operations refer to Cosmos sessions, terminal panes, views, retained output and Actions. The terminal multiplexer is an implementation detail. A backend socket name or option is not a public target. `workspace_info()` returns an opaque `service_id`, the workspace scope/capabilities, and explicit host-command/isolation limits; it does not return the backend socket.

The existing `cosmos_terminal` tool prefix and `$session` / `@window` / `%pane` handles remain compatibility interfaces. They identify objects in this connected Cosmos workspace, not arbitrary host services. The `session:pane` display identifier is resolved by Cosmos. This increment does not rename every legacy metadata field; integrations must not interpret a compatibility handle as permission to address another service.

## Service binding

The native launcher records the existing managed service incarnation in private process context. Tool connections verify it using backend process identity plus process start identity on Linux. Authenticated conversations sharing a tool process also share this connection binding. A service-name reuse or target disappearance fails closed; a new service never replaces the old one silently. Standalone tool callers without a launch binding bind on their first successful workspace metadata query. A missing/empty workspace is rejected rather than falling back to a default host service.

Terminal target validation, retained-history reads and Action discovery/dispatch use the same binding. Actions validate the workspace before dispatch to the coordinator/UI. A failed connection requires an explicit new connection and fresh target discovery. Metadata validation and delivery are separate operations, so this is not an atomic operating-system transaction or a hard real-time guarantee.

## Host execution is separate

The default Cosmos Agent configuration explicitly asks for native `shell` permission. A workspace-management or pane-control grant never includes host shell execution. Existing user permission rules, including saved approvals, remain governed by OpenCode; the explicit default ask is not a new transient capability or an OS restriction. The model prompt directs normal workspace interaction through Cosmos tools and forbids using Shell to bypass denied/private/paused operations.

An approved host command still runs with the user's OS privileges. Other execution paths and trusted same-user programs may also access local resources. Renaming tools, hiding environment variables or asking for Shell permission cannot prevent access to unrelated terminal-multiplexer sockets. No filesystem/socket sandbox is implemented by this interface. Enforced host isolation requires a separately designed process/container/socket-access boundary.
