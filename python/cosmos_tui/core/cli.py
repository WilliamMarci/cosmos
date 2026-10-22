"""CLI parsing is independent of the terminal renderer and coordinator startup."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

from cosmos_tui.core.metadata import VERSION
from cosmos_tui.core.paths import PROJECT_ROOT


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parser():
    cli = argparse.ArgumentParser(
        prog="cosmos",
        description="Cosmos persistent terminal workspace",
        epilog="With no command, attach to 'main'. 'cosmos SESSION' is shorthand for attach.\n"
        "Inside Cosmos: Ctrl+B then p for settings, Ctrl+P for actions, Ctrl+B then s to switch.\n"
        "Environment: COSMOS_BINARY overrides the coordinator; COSMOS_TMUX overrides tmux.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cli.add_argument("--version", action="version", version=f"Cosmos {VERSION}")
    commands = cli.add_subparsers(dest="command", metavar="COMMAND")
    attach = commands.add_parser(
        "attach", help="create or reconnect to a retained session"
    )
    attach.add_argument(
        "session", nargs="?", default="main", help="session name (default: main)"
    )
    attach.add_argument("--debug", action="store_true", help="enable DEBUG diagnostics")
    attach.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING"
    )
    attach.add_argument(
        "--log-file", help="diagnostic log file (default: XDG state cosmos/logs/ui.log)"
    )
    session_group = commands.add_parser(
        "session", help="manage retained sessions and export history"
    )
    session_commands = session_group.add_subparsers(
        dest="session_command", required=True
    )
    for name, container in (("new", commands), ("new", session_commands)):
        new = container.add_parser(
            name, help="create a new session; fail if it already exists"
        )
        new.add_argument("session", help="new session name")
        new.add_argument(
            "--detached",
            "-d",
            action="store_true",
            help="create without opening the UI",
        )
        new.add_argument("--cwd", help="initial working directory")
    for name, container in (("sessions", commands), ("list", session_commands)):
        listing = container.add_parser(
            name, help="list retained sessions without starting a service"
        )
        listing.add_argument(
            "--json", action="store_true", help="machine-readable output"
        )
    for name, container in (("history", commands), ("history", session_commands)):
        history = container.add_parser(
            name, help="export retained output from a session's panes"
        )
        history.add_argument("session", nargs="?", default="main")
        history.add_argument("--pane", help="export only this pane ID, such as %%0")
        history.add_argument(
            "--lines",
            type=positive_integer,
            help="last N retained physical lines per pane",
        )
        history.add_argument(
            "--ansi", action="store_true", help="retain ANSI color escapes"
        )
        history.add_argument(
            "--json", action="store_true", help="include pane metadata as JSON"
        )
        history.add_argument(
            "--output", "-o", help="write UTF-8 output to a file instead of stdout"
        )
    session_commands.add_parser(
        "attach",
        parents=[attach],
        add_help=False,
        help="create or reconnect to a session",
    )
    for name, help_text in {
        "daemon": "run the coordinator in the foreground",
        "stop": "stop the coordinator and managed Mods; retain tmux applications",
        "doctor": "print environment and dependency diagnostics as JSON",
        "config": "print the effective coordinator configuration",
        "events": "stream coordinator events until interrupted",
        "cache-clear": "clear the viewer disk cache",
    }.items():
        commands.add_parser(name, help=help_text, description=help_text)
    mod = commands.add_parser("mod", help="manage trusted external Mods")
    operations = mod.add_subparsers(dest="operation")
    operations.add_parser("list", help="list registered Mods")
    operations.add_parser("add", help="register a TOML or JSON manifest").add_argument(
        "manifest"
    )
    for name in ("start", "stop", "remove"):
        operations.add_parser(name, help=f"{name} a registered Mod").add_argument("id")
    action = commands.add_parser("action", help="invoke a registered Mod action")
    action.add_argument("id", help="action ID from actions.list")
    rpc = commands.add_parser("rpc", help="call an existing coordinator RPC method")
    rpc.add_argument("method")
    rpc.add_argument(
        "params", nargs="?", default="{}", help="JSON object (default: {})"
    )
    commands.add_parser(
        "open", help="open a file in the current Cosmos pane"
    ).add_argument("file")
    completion = commands.add_parser("completion", help="print shell completion code")
    completion.add_argument(
        "shell", choices=["bash"], help="source with: source <(cosmos completion bash)"
    )
    help_parser = commands.add_parser("help", help="show general or command help")
    help_parser.add_argument("topic", nargs="?", choices=list(commands.choices))
    return cli, commands.choices


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cli, commands = parser()
    if not argv or (
        argv[0] not in commands and argv[0] not in ("-h", "--help", "--version")
    ):
        argv.insert(0, "attach")
    args = cli.parse_args(argv)
    if args.command == "help":
        (commands[args.topic] if args.topic else cli).print_help()
        return
    if args.command == "completion":
        print((PROJECT_ROOT / "shell/completions/cosmos.bash").read_text(), end="")
        return
    try:
        operation = args.session_command if args.command == "session" else args.command
        if operation in ("new", "sessions", "list", "history"):
            from cosmos_tui.terminal import sessions

            if operation == "new":
                asyncio.run(sessions.create(args.session, args.cwd))
                if args.detached:
                    print(args.session)
                    return
                args.debug, args.log_level, args.log_file = False, "WARNING", None
                operation = "attach"
            elif operation in ("sessions", "list"):
                rows = asyncio.run(sessions.listing())
                if args.json:
                    print(json.dumps(rows, indent=2))
                else:
                    for row in rows:
                        print(f"{row['name']}\t{row['windows']} window(s)")
                return
            else:
                rows = asyncio.run(
                    sessions.history(args.session, args.pane, args.lines, args.ansi)
                )
                output = sessions.format_history(rows, args.json)
                if args.output:
                    Path(args.output).expanduser().write_text(output, encoding="utf-8")
                else:
                    print(output, end="")
                return
        if operation == "attach":
            from cosmos_tui.runtime.bootstrap import run

            run(args)
            return
        binary = Path(
            os.environ.get("COSMOS_BINARY", PROJECT_ROOT / "target/release/cosmos")
        )
        raise SystemExit(subprocess.call([str(binary), *argv]))
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        cli.exit(1, f"cosmos: {error}\n")
