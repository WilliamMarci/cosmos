# Cosmos command line

The public entry is `cosmos` at the project root. It resolves symbolic links before locating Python and assets, so linking it into `~/.local/bin` works. The project `.venv` and built coordinator must exist; packaged installations use `bin/cosmos` as the coordinator. Only the Python UI is public.

```bash
cosmos                         # create or reconnect to main
cosmos research                # shorthand for attach research
cosmos a                       # short form of attach
cosmos a -s research           # explicit session flag
cosmos n -s research           # create, then open the UI
cosmos --help
cosmos a --help
cosmos help a
cosmos --version
```

Commands accept a canonical name, a compatibility alias, or any unique prefix. The help lists the shortest accepted form in brackets, for example `[a]ttach`, `[n]ew`, `[l]ist`, `[ex]ists` and `[hi]story`. tmux long names such as `attach-session`, `new-session` and `has-session` remain accepted but are hidden from the main help. `cosmos h` is ambiguous; the error lists the candidates and shows how to attach to a session with that literal name.

UI options: `--debug`, `--log-level DEBUG|INFO|WARNING|ERROR`, `--log-file PATH` and `--mouse-mode auto|cell|pixel`. They work with `attach`, `new`, and the shorthand invocation. Logs default to the XDG state directory, `cosmos/logs/ui.log`.

Management commands, all with `--help`:

- `daemon`: foreground coordinator.
- `stop`: stop the coordinator and its Mods; retain tmux applications.
- `doctor`, `config`: diagnostic JSON and effective configuration.
- `events`: stream service events until interrupted.
- `mod list`, `mod add MANIFEST`, `mod start ID`, `mod stop ID`, `mod remove ID`.
- `action ID`: launch a registered Mod action.
- `rpc METHOD [JSON]`: call an existing coordinator without starting one.
- `open FILE`: request the integrated viewer in the current Cosmos pane.
- `cache-clear`: clear the persistent reader disk cache.
- `completion bash`: print completion code without starting services.

`COSMOS_BINARY` overrides the coordinator executable, `COSMOS_TMUX` selects tmux, and `COSMOS_TMUX_SOCKET` selects the isolated tmux server. Shell initialization and `COSMOS_RC` are documented in [shell.md](shell.md).

## Bash completion

Load completion into an already running Bash:

```bash
source <(cosmos completion bash)
```

For future shells using bash-completion, install the supplied file under its standard user directory:

```bash
mkdir -p ~/.local/share/bash-completion/completions
cosmos completion bash > ~/.local/share/bash-completion/completions/cosmos
```

Completion covers commands, subcommands, options, log levels, file paths and common RPC methods. It does not start a coordinator or enumerate live Mod IDs or sessions. Bash is the currently supported shell; other shells are not advertised.

## Sessions and history

The flat commands are canonical. `cosmos session COMMAND ...` groups the same operations for compatibility. Every session-targeting command accepts `-s/--session NAME`; `attach`, `new`, `kill`, `exists` and `history` also accept the name as the first positional argument.

| Command | Compatibility aliases | Purpose |
| --- | --- | --- |
| `[a]ttach [-s NAME] [NAME]` | `a`, `attach-session` | reconnect, or create when absent |
| `[n]ew [-s NAME] [NAME] [-d] [-c DIR]` | `n`, `new-session` | create; fail if the name exists |
| `[l]ist [-j]` | `l`, `ls`, `sessions`, `list-sessions` | list retained sessions |
| `[k]ill [-s NAME] [NAME]` | `k`, `kill-session` | destroy a session |
| `[ex]ists [-s NAME] [NAME]` | `ex`, `has`, `has-session` | exit 0 when present, 1 when absent |
| `[re]name [-s OLD] [OLD] NEW` | `re`, `rename-session` | rename a session |
| `[hi]story [-s NAME] [NAME] [options]` | `hi` | export retained output |

```bash
cosmos list                               # also: cosmos ls, cosmos sessions
cosmos n -s research                      # create, then open the UI
cosmos n -d -s research -c ~/work         # detached, explicit working directory
cosmos session n -s research              # grouped compatibility form
cosmos a research                         # attach; create if absent
cosmos exists research                    # shell test: 0 present, 1 absent
cosmos rename -s research archive
cosmos kill research
cosmos history research --pane %0 --lines 200
cosmos history -s research --output research.txt
cosmos history research --json --output research.json
```

New session names use letters, digits, `_` and `-`. `new` refuses an existing name; `attach` reconnects or creates when absent. When `attach` creates a missing session, the UI publishes a session-scoped info notification such as `Session 'research' not found; created`; reconnects do not notify. `--detached` creates without starting a UI or coordinator. Listing, existence checks and history also work without a coordinator and do not start one. The selected Cosmos Tmux socket is shared with the UI, separate from ordinary tmux.

Names are exact Cosmos session identities. Cosmos resolves a name to the stable tmux `$N` ID before operating, so a session named `research` never matches `research2` by tmux's prefix rules. A name that is also a command or unique command prefix is reserved for the command; use `cosmos attach NAME` to reach such a session.

History defaults to **all retained output plus the current screen, for every pane in the named session**, including windows that are not selected. Multiple panes have identifying headers; `--json` emits records with `session`, `window`, `pane_index`, `pane`, and `text`. `--pane` restricts to one exact pane ID in that session. `--lines N` takes the final N physical lines per pane; wrapped rows remain separate. `--ansi` preserves color escape sequences; default output is plain text. `--output` writes UTF-8 and replaces an existing destination file.

This is a snapshot of tmux's retained terminal output, not a command audit log, Bash history, or an archive of previous Cosmos launches. Evicted scrollback and closed panes cannot be exported. Live programs may continue producing output while panes are captured; the export is not an atomic cross-pane snapshot. A missing session is an error; an empty session list prints nothing (`[]` with `--json`).

The flat commands, their common aliases, nested session operations, uniform session flags and export options are included in Bash completion. Session names and live Mod IDs are not enumerated by completion.

## Client mouse coordinates

`cosmos --mouse-mode auto|cell|pixel` sets this connection's mouse mode. The option also works on `attach`, `new`, and their `session` group forms. Auto defaults to Cell until capability and geometry are confirmed; Cell is intended for compatibility with remote/mobile clients. Settings → Input → Mouse mode changes the current client immediately. No coordinator setting is modified, and mouse selection is independent of image rendering. See mouse.md for negotiation and fallback details.

`cosmos --version` prints `Cosmos Arche 0.2.0-dev.1 (development)`. The codename/channel identify the development release; session command and protocol version semantics are unchanged.

`cosmos cache-clear` now clears the persistent Python Reader cache with the same lock/generation protocol as Settings → Reader; running clients keep their in-memory frames. The older viewer.cache.clear RPC remains the legacy Rust cache operation.

## Stable session and pane IDs

Session targets accept exact names or the Tmux server's stable `$ID`. Quote dollar IDs so the shell does not expand them:

```bash
cosmos list
cosmos attach '$3'
cosmos exists '$3'
cosmos rename '$3' research
cosmos history '$3' --pane '%8' --json
```

IDs survive renaming for the lifetime of that Tmux server. A missing ID is an error, and `cosmos new` requires a name. List output begins with the session ID; JSON session listings expose it as `id`. History JSON additionally includes `session_id`. The existing `--pane '%ID'` option checks that the pane belongs to the requested session. Switch displays stable `$`/`@`/`%` IDs separately from the local window/pane indices; see [Switch](switch.md).
