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
