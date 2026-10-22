# Cosmos command line

The public entry is `cosmos` at the project root. It resolves symbolic links before locating Python and assets, so linking it into `~/.local/bin` works. The project `.venv` and built coordinator must exist; packaged installations use `bin/cosmos` as the coordinator. Only the Python UI is public.

```bash
cosmos                         # create or reconnect to main
cosmos research                # shorthand session name
cosmos attach research --debug # explicit form; also works for reserved command names
cosmos --help
cosmos attach --help
cosmos help mod
cosmos --version
```

UI options: `--debug`, `--log-level DEBUG|INFO|WARNING|ERROR`, `--log-file PATH`. These follow `attach`, or can be used with the shorthand invocation. Logs default to the XDG state directory, `cosmos/logs/ui.log`.

Management commands, all with `--help`:

- `daemon`: foreground coordinator.
- `stop`: stop the coordinator and its Mods; retain tmux applications.
- `doctor`, `config`: diagnostic JSON and effective configuration.
- `events`: stream service events until interrupted.
- `mod list`, `mod add MANIFEST`, `mod start ID`, `mod stop ID`, `mod remove ID`.
- `action ID`: launch a registered Mod action.
- `rpc METHOD [JSON]`: call an existing coordinator without starting one.
- `open FILE`: request the integrated viewer in the current Cosmos pane.
- `cache-clear`: clear the viewer disk cache.
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

```bash
cosmos session list                       # also: cosmos sessions
cosmos session new research               # create, then open the UI
cosmos new research --detached --cwd ~/work
cosmos session attach research            # also: cosmos attach research
cosmos history research                   # also: cosmos session history research
cosmos history research --pane %0 --lines 200
cosmos history research --output research.txt
cosmos history research --json --output research.json
```

New session names use letters, digits, `_` and `-`. `new` refuses an existing name; `attach` reconnects or creates when absent. `--detached` creates without starting a UI or coordinator. Listing and history also work without a coordinator and do not start one. The selected Cosmos Tmux socket is shared with the UI, separate from ordinary tmux.

History defaults to **all retained output plus the current screen, for every pane in the named session**, including windows that are not selected. Multiple panes have identifying headers; `--json` emits records with `session`, `window`, `pane_index`, `pane`, and `text`. `--pane` restricts to one exact pane ID in that session. `--lines N` takes the final N physical lines per pane; wrapped rows remain separate. `--ansi` preserves color escape sequences; default output is plain text. `--output` writes UTF-8 and replaces an existing destination file.

This is a snapshot of tmux's retained terminal output, not a command audit log, Bash history, or an archive of previous Cosmos launches. Evicted scrollback and closed panes cannot be exported. Live programs may continue producing output while panes are captured; the export is not an atomic cross-pane snapshot. A missing session is an error; an empty session list prints nothing (`[]` with `--json`).

The new commands, nested session operations and export options are included in Bash completion. Session names and live Mod IDs are not enumerated by completion.

## Client mouse coordinates

`cosmos --mouse-mode auto|cell|pixel` sets this connection's mouse mode. The option also works on attach and session attach. Auto defaults to Cell until capability and geometry are confirmed; Cell is intended for compatibility with remote/mobile clients. Settings → Input → Mouse mode changes the current client immediately. No coordinator setting is modified, and mouse selection is independent of image rendering. See mouse.md for negotiation and fallback details.
