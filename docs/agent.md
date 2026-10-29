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

The launcher runs `python -m cosmos_tui.features.agent launch --socket SOCKET --source-pane %ID`, then executes the patched frontend with `--standalone`. Each frontend owns a private OpenCode server. SSH or Cosmos UI detachment leaves its Tmux process running; reconnecting redraws the retained pane. Closing the Agent frontend ends that private server. OpenCode owns conversation persistence; databases are stored below Cosmos's own data directory. The source runtime uses `opencode-local.db`, the bundled build uses `opencode-cosmos.db`, and the system route follows its installed channel within that same private data root. Cosmos owns provider configuration and credentials; the frontend retains its provider picker and native permission UI. The initial default is a direct DeepSeek API model, without OpenCode Console/free-model fallback or automatic updates.

Cosmos injects an in-memory `OPENCODE_CONFIG_CONTENT` configuration for the `cosmos` primary agent and `cosmos_terminal` / `cosmos_actions` MCP servers. It does **not** merge inherited OpenCode configuration content, plugin configuration or credentials. Additional Agent configuration belongs in `${XDG_CONFIG_HOME:-~/.config}/cosmos/agent/opencode.json`. Standard OpenCode/Claude/.agents configuration and project `.opencode`/`opencode.json` discovery are disabled. A shared ordinary OpenCode server is not reused.

All private Agent settings, credentials, conversations, caches, logs, temporary files, personal skills and default exports live below `${XDG_CONFIG_HOME:-~/.config}/cosmos/agent/`. The profile directory is mode **0700**. Files are **0600**, directories and owner-executable helpers **0700**; launch uses umask **077**. Files owned by another UID and symlinks escaping the profile are rejected. This is Unix user isolation, not protection from root or other processes running as the same user. Project skills remain in the explicitly selected project, and exports to a user-specified destination remain there (created mode 0600, never overwritten).

Configure a direct API without putting the key in shell history:

```sh
cosmos agent configure --provider deepseek --model deepseek-flash --base-url https://api.deepseek.com/v1 --set-key
```

The key is prompted without echo. `profile.json` stores provider/model/base URL, `credentials.json` maps provider IDs to keys; keys are injected into the Agent process environment, never argv or generated configuration. Other OpenAI-compatible APIs use their provider ID/model/base URL; `anthropic` uses the Anthropic adapter and `deepseek` the DeepSeek adapter. No existing ordinary OpenCode credentials are imported. An unconfigured key must be supplied before using the API. Model availability and billing belong to the chosen provider.

OpenCode's XDG config/data/cache/state bases are redirected to this profile's `config/`, `data/`, `cache/`, `state/` subdirectories; native databases retain their channel-specific names under `data/opencode/`. `COSMOS_AGENT_PROFILE` carries the original root into child tools despite those redirected XDG variables. `HOME` remains unchanged for terminal applications. Additional native configuration and optional MCP declarations belong in `opencode.json` here. The patched runtime disables its OpenCode Console provider registration; the system runtime receives the direct default, free-model disable flag and hosted-provider deny policy.

For installations using the older split Cosmos directories, close Agent frontends and run `cosmos agent migrate` **before starting the new Agent**. It moves only old Cosmos personal skills and `cosmos/agent/opencode` data/cache/state directories into this profile, refuses existing destinations or legacy symlinks, and does not touch ordinary OpenCode data. Existing conversations in different runtime channels are not converted between database names.

The initial default theme is **cosmos**, installed in `themes/cosmos.json` and selected in `cli.json`. It uses the Cosmos dark surface, blue/teal accents, amber highlights and semantic red/green. Later user theme selections are preserved. The source/bundled runtime includes it as a built-in theme; the system runtime uses the installed custom theme file.

Cosmos's built-in tools are injected separately from optional MCPs declared in the Cosmos-owned configuration file. Configured instructions, skills, commands or plugins can be explicitly added there; there is no automatic import of the corresponding ordinary Agent directories. See [Agent skills](agent-skills.md) for the permitted default skill roots.

The home screen and exit wordmark use the canonical Cosmos glyphs in theme-relative monochrome, with **powered by opencode** underneath. Semantic normal/muted text roles adapt to OpenCode's selected theme. Narrow terminals display a compact COSMOS label. Upstream source and provenance are recorded in `integrations/opencode/`.

## Reusable software skills

Cosmos skills use OpenCode's native discovery and skill tool. Bundled, personal and project skill libraries are injected at launch. `/cosmos-learn` starts a software-learning task; `/cosmos-export-skill` saves the observed method as a portable `SKILL.md` directory. See [Agent skills](agent-skills.md) for prompts, paths and ZIP export.

## Cosmos Actions

`cosmos_actions.list_actions` discovers service/Mod actions and connected clients' live UI actions. `invoke_action` routes them through the coordinator or existing UI dispatcher, with explicit client selection when needed. See [Agent Actions](agent-actions.md) for scopes, parameters, acknowledgements and lifecycle.

## Terminal tools

The MCP server speaks newline-delimited stdio JSON-RPC. It has no listening network port. It is pinned to the Cosmos Tmux service supplied by the launcher; it does not attach a control client, resize user panes, or use the caller's inherited `TMUX` socket. Tools apply to all sessions in that service. An Agent can inspect the following tools through OpenCode's normal tool discovery:

- `list_sessions()` groups all sessions by stable `$ID`, with names and window/pane IDs.
- `create_session(name, source_pane)` creates a retained named session in the source cwd without interrupting existing work.
- `rename_target(target, name)` renames a stable `$session`, `@window` or `%pane` target; pane labels use the same `@cosmos_name` field as Switch.
- `focus_pane(pane, client=None)` selects a pane through a connected Cosmos client and updates its session/window state. An explicit client is required when several clients exist. An open modal must be closed first.
- `export_history(session, output=None)` writes retained terminal output and pane metadata as JSON. Default: private `exports/terminal-<id>-<timestamp>.json`; explicit destinations never overwrite. The per-pane bound is 16 MiB; oversized history returns an error rather than truncating.
- `list_panes()` returns stable session/window/pane IDs, display indices, dimensions, cursor, cwd, running program, alternate-screen/copy-mode and mouse flags.
- `read_screen(pane, history=0, wait_ms=0)` captures the current TUI character grid, with optional retained history (0–2000 lines) and a bounded wait (0–2000 ms). The result includes pane metadata and a `truncated` flag. Text is limited to 64 KiB. Capture does not leave alternate screen or move the user's scroll position.
- `send_text(pane, text)` pastes at most 32 KiB of UTF-8 using an isolated, disposable Tmux buffer and bracketed paste when the application supports it. It adds no Return. Embedded newlines may execute in applications without bracketed paste. Escape/control characters are rejected; use `send_keys` for controls.
- `send_keys(pane, keys)` sends 1–64 ordered Tmux key names or single printable ASCII keys. Examples: `["Escape"]`, `["C-c"]`, `["Tab", "Down", "Enter"]`, `["PageDown"]`. Arguments are passed directly to Tmux with an option terminator, never interpolated into a shell command.
- `mouse(pane, x, y, button="left", action="click")` uses one-based pane-local cells. Buttons: left, middle, right, wheel_up, wheel_down. Actions: click, press, release, move. It reuses Cosmos's SGR/UTF-8/X10 encoder and checks application tracking/motion flags. Unsupported tracking or out-of-bounds coordinates produce a tool error; no guessed click is sent.
- `create_terminal(source_pane)` creates a retained Bash window in the source session and cwd, without selecting it. It returns the new stable pane ID and initial screen. It does not close or replace existing work.

Every targeted operation validates a stable `%ID` against the selected service. A closed pane produces a tool error. The bridge does not silently retarget another pane. Returned application output is untrusted data, not authorization or new instructions. It is a text-grid bridge: it does not send image pixels or expose Cosmos-owned Reader/Files overlays as terminal content.

## Permissions

OpenCode tool names are `cosmos_terminal_<tool>`. Default permission rules allow `list_sessions`, `list_panes` and `read_screen`; `send_text`, `send_keys`, `mouse`, `create_terminal`, session creation/rename/focus and history export require OpenCode's normal confirmation. The bridge itself is a trusted local program, not a sandbox. Users can change tool policies using OpenCode's permission mechanisms. The command assistant's File access setting does not govern this full Agent.

`config/cosmos-agent-prompt.md` tells the agent to inspect before acting, prefer a new terminal for new tasks, send short input sequences, and read back the result. Successful input delivery alone is not treated as task completion.

## Validation

`dev/test_cosmos_agent.py` runs against an isolated Tmux service and real Vim. It covers alternate-screen capture, Unicode paste without implicit Return, key-driven navigation/paging, mouse click/scroll, background-terminal cwd/session inheritance, missing-pane errors and MCP stdio discovery/calls. It does not call a paid model. The OpenCode-side test checks the actual configuration schema and read/ask/deny rule matching; a real terminal launch verifies the branded frontend and MCP connection.

## Conversation exports

`cosmos agent export ses_ID [--output new-file.json]` exports a native Agent conversation as sanitized JSON to the private `exports/` directory by default. It uses the selected runtime's session-export API and database channel; it does not call a model. Sanitization follows the native exporter and does not guarantee arbitrary secrets in message text are removed. This differs from `cosmos_terminal.export_history`, and from `cosmos history`, which export retained terminal output. Neither recovers history already discarded by Tmux.

## Module boundaries

`profile.py` owns private storage and direct provider settings; `configuration.py` assembles the native Agent/MCP configuration; `launch.py` selects and launches the runtime. `sessions.py` extends terminal operations with session management and terminal-history export. `conversations.py` exports native model conversations. `theme.py` installs the initial theme without overwriting user choices; `migration.py` handles earlier Cosmos-only storage. `actions.py` and `action_ui.py` retain the service/client Action boundary.

## Child application shortcut conflicts

`Leader → F12` toggles **keyboard passthrough** for the current Cosmos client. In a terminal pane, keys bypass Cosmos Actions, pane shortcuts and IME and go directly to the child application; for example, `Ctrl+P` opens the Agent's own command menu. The configured passthrough toggle remains reserved so it can restore Cosmos controls. A Leader followed by any other key is forwarded as both original keys. Mouse controls and Cosmos dialogs remain available; Reader/Files surfaces retain their own controls. The status bar displays bold `KEYS OFF` directly after the session name when space permits. This temporary state is not persisted or shared with other clients. `global.keyboard_passthrough` is available in Actions and Settings → Keybindings; its default binding is `leader+f12`.
