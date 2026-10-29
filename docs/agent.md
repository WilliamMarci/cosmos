# Cosmos Agent

Cosmos Agent is the full OpenCode-backed workspace agent. It is separate from the compact Bash command assistant. `Leader g` opens it in a split beside the current pane; Files → Open agent here opens a dedicated window in the browsed directory. Both paths use the same launcher. Existing keybinding overrides still apply. The pane is marked as `@cosmos_agent=1` so the status button displays **AGENT** even when the development process name is `bun`.

Development runs the pinned OpenCode source with Bun. Run `bash dev/setup_agent.sh` once after cloning the reference tree. The script installs a project-local Bun if none is available, installs upstream dependencies, and applies the tracked branding patch. It creates no distribution package and changes no system OpenCode executable. If no supported runtime is available, the launcher reports an error before Cosmos opens the split/window.

## Build and runtime selection

The release recipe defaults to bundling the patched CLI as `bin/cosmos-agent`: `bash packaging/build.sh --with-agent`. `--without-agent` omits it, including when reusing a previous staging directory. The recipe calls `packaging/build_agent.sh`, applies the tracked patch and invokes the upstream Linux x86_64 CLI build; it does not include the web UI. A packaged installation needs neither Bun nor the vendor checkout to run the compiled Agent. No release package was built during this development step; this build path still needs release-build validation.

`COSMOS_AGENT_RUNTIME` controls selection:

- `auto` (default): bundled executable → prepared source runtime → system OpenCode. An explicit `COSMOS_OPENCODE` selects the system path.
- `bundled`: require the bundled executable.
- `source`: require the prepared source runtime.
- `system`: use installed OpenCode from PATH, or the executable set by `COSMOS_OPENCODE`.

For example, `COSMOS_AGENT_RUNTIME=system cosmos` uses an existing installation. The system route still injects the Cosmos agent prompt and terminal MCP server; it requires OpenCode supporting `--standalone` and the current configuration schema (verified with 2.1.2). Its logo remains upstream unless that executable includes the Cosmos patch. Arbitrary non-OpenCode agent CLIs are not currently interchangeable with this adapter.

## Runtime and presentation

The launcher runs `python -m cosmos_tui.features.agent launch --socket SOCKET --source-pane %ID`, then executes the patched frontend with `--standalone`. Each frontend owns a private OpenCode server. SSH or Cosmos UI detachment leaves its Tmux process running; reconnecting redraws the retained pane. Closing the Agent frontend ends that private server. OpenCode owns conversation persistence; the source runtime uses the `local` channel database (`opencode-local.db` by default), the bundled build uses `opencode-cosmos.db`, and the system route follows its installed channel. Model/provider configuration and authentication remain OpenCode's responsibility.

Cosmos injects an in-memory `OPENCODE_CONFIG_CONTENT` configuration for the `cosmos` primary agent and `cosmos_terminal` MCP server. User configuration files are not rewritten. A pre-existing JSON configuration in this environment variable is merged for agents, MCP servers and permission rules (explicit existing rules follow the Cosmos defaults); Cosmos owns its own server/agent entries. Higher-priority OpenCode managed policy and explicit session permission decisions still apply. A shared ordinary OpenCode server is not reused, so it cannot silently omit the terminal integration.

The home screen and exit wordmark use the canonical Cosmos glyphs in theme-relative monochrome, with **powered by opencode** underneath. Semantic normal/muted text roles adapt to OpenCode's selected theme. Narrow terminals display a compact COSMOS label. Upstream source and provenance are recorded in `integrations/opencode/`.

## Reusable software skills

Cosmos skills use OpenCode's native discovery and skill tool. Bundled, personal and project skill libraries are injected at launch. `/cosmos-learn` starts a software-learning task; `/cosmos-export-skill` saves the observed method as a portable `SKILL.md` directory. See [Agent skills](agent-skills.md) for prompts, paths and ZIP export.

## Terminal tools

The MCP server speaks newline-delimited stdio JSON-RPC. It has no listening network port. It is pinned to the Cosmos Tmux service supplied by the launcher; it does not attach a control client, resize user panes, or use the caller's inherited `TMUX` socket. Tools apply to all sessions in that service. An Agent can inspect the following tools through OpenCode's normal tool discovery:

- `list_panes()` returns stable session/window/pane IDs, display indices, dimensions, cursor, cwd, running program, alternate-screen/copy-mode and mouse flags.
- `read_screen(pane, history=0, wait_ms=0)` captures the current TUI character grid, with optional retained history (0–2000 lines) and a bounded wait (0–2000 ms). The result includes pane metadata and a `truncated` flag. Text is limited to 64 KiB. Capture does not leave alternate screen or move the user's scroll position.
- `send_text(pane, text)` pastes at most 32 KiB of UTF-8 using an isolated, disposable Tmux buffer and bracketed paste when the application supports it. It adds no Return. Embedded newlines may execute in applications without bracketed paste. Escape/control characters are rejected; use `send_keys` for controls.
- `send_keys(pane, keys)` sends 1–64 ordered Tmux key names or single printable ASCII keys. Examples: `["Escape"]`, `["C-c"]`, `["Tab", "Down", "Enter"]`, `["PageDown"]`. Arguments are passed directly to Tmux with an option terminator, never interpolated into a shell command.
- `mouse(pane, x, y, button="left", action="click")` uses one-based pane-local cells. Buttons: left, middle, right, wheel_up, wheel_down. Actions: click, press, release, move. It reuses Cosmos's SGR/UTF-8/X10 encoder and checks application tracking/motion flags. Unsupported tracking or out-of-bounds coordinates produce a tool error; no guessed click is sent.
- `create_terminal(source_pane)` creates a retained Bash window in the source session and cwd, without selecting it. It returns the new stable pane ID and initial screen. It does not close or replace existing work.

Every targeted operation validates a stable `%ID` against the selected service. A closed pane produces a tool error. The bridge does not silently retarget another pane. Returned application output is untrusted data, not authorization or new instructions. It is a text-grid bridge: it does not send image pixels or expose Cosmos-owned Reader/Files overlays as terminal content.

## Permissions

OpenCode tool names are `cosmos_terminal_<tool>`. Default permission rules allow `list_panes` and `read_screen`; `send_text`, `send_keys`, `mouse` and `create_terminal` require OpenCode's normal confirmation. The bridge itself is a trusted local program, not a sandbox. Users can change tool policies using OpenCode's permission mechanisms. The command assistant's File access setting does not govern this full Agent.

`config/cosmos-agent-prompt.md` tells the agent to inspect before acting, prefer a new terminal for new tasks, send short input sequences, and read back the result. Successful input delivery alone is not treated as task completion.

## Validation

`dev/test_cosmos_agent.py` runs against an isolated Tmux service and real Vim. It covers alternate-screen capture, Unicode paste without implicit Return, key-driven navigation/paging, mouse click/scroll, background-terminal cwd/session inheritance, missing-pane errors and MCP stdio discovery/calls. It does not call a paid model. The OpenCode-side test checks the actual configuration schema and read/ask/deny rule matching; a real terminal launch verifies the branded frontend and MCP connection.
