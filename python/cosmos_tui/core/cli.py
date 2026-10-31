"""CLI parsing is independent of the terminal renderer and coordinator startup."""

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

from cosmos_tui.core.metadata import DISPLAY_VERSION
from cosmos_tui.core.paths import PROJECT_ROOT


class CLIError(ValueError):
    """A command could not be resolved before argparse parsing."""


@dataclass(frozen=True)
class CommandSpec:
    name: str
    parser: str
    aliases: tuple[str, ...]
    summary: str


SESSION_COMMANDS = (
    CommandSpec(
        "attach",
        "[a]ttach",
        ("a", "attach-session"),
        "create or reconnect to a session",
    ),
    CommandSpec(
        "new",
        "[n]ew",
        ("n", "new-session"),
        "create a session; fail if it already exists",
    ),
    CommandSpec(
        "list",
        "[l]ist",
        ("ls", "sessions", "list-sessions"),
        "list retained sessions without starting a service",
    ),
    CommandSpec("kill", "[k]ill", ("kill-session",), "destroy a session"),
    CommandSpec(
        "exists",
        "[ex]ists",
        ("ex", "has", "has-session"),
        "check whether a session exists",
    ),
    CommandSpec("rename", "[re]name", ("re", "rename-session"), "rename a session"),
    CommandSpec(
        "history",
        "[hi]story",
        ("hi",),
        "export retained output from a session's panes",
    ),
)

TOP_LEVEL_COMMANDS = SESSION_COMMANDS + (
    CommandSpec(
        "agent", "[ag]ent", (), "configure Cosmos Agent or export its conversations"
    ),
    CommandSpec("session", "session", (), "manage sessions through a command group"),
    CommandSpec("daemon", "[da]emon", (), "run the coordinator in the foreground"),
    CommandSpec(
        "stop",
        "[st]op",
        (),
        "stop the coordinator and managed Mods; retain tmux applications",
    ),
    CommandSpec(
        "doctor",
        "[do]ctor",
        (),
        "print environment and dependency diagnostics as JSON",
    ),
    CommandSpec(
        "config",
        "[con]fig",
        (),
        "print the effective coordinator configuration",
    ),
    CommandSpec(
        "events",
        "[ev]ents",
        (),
        "stream coordinator events until interrupted",
    ),
    CommandSpec(
        "cache-clear", "[ca]che-clear", (), "clear the persistent reader disk cache"
    ),
    CommandSpec("mod", "[m]od", (), "manage trusted external Mods"),
    CommandSpec("action", "[ac]tion", (), "invoke a registered Mod action"),
    CommandSpec("rpc", "[rp]c", (), "call an existing coordinator RPC method"),
    CommandSpec(
        "open", "[o]pen", (), "open a file or directory in the current Cosmos pane"
    ),
    CommandSpec("completion", "[com]pletion", (), "print shell completion code"),
    CommandSpec("help", "[he]lp", (), "show general or command help"),
)

PARSER_NAMES = {spec.parser: spec.name for spec in TOP_LEVEL_COMMANDS}
MOUSE_MODES = ("auto", "cell", "pixel")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def resolve_command(token, commands):
    """Resolve a canonical name, alias, or unique prefix to one command."""
    for command in commands:
        if token == command.name or token in command.aliases:
            return command
    matches = {}
    for command in commands:
        surfaces = (command.name, *command.aliases)
        if any(surface.startswith(token) for surface in surfaces):
            matches[command.name] = command
    if len(matches) == 1:
        return next(iter(matches.values()))
    if matches:
        names = ", ".join(sorted(matches))
        raise CLIError(
            f"ambiguous command: {token}, could be: {names}. "
            f"For a session named {token!r}, use: cosmos attach {token}"
        )
    return None


def canonicalize(argv):
    """Translate aliases and prefixes to parser names before argparse sees them."""
    if not argv:
        return ["[a]ttach"], "attach"
    first = argv[0]
    if first in ("-h", "--help", "--version"):
        return argv, None
    if first.startswith("-"):
        return ["[a]ttach", *argv], "attach"
    command = resolve_command(first, TOP_LEVEL_COMMANDS)
    if command is None:
        return ["[a]ttach", *argv], "attach"
    if command.name == "session" and len(argv) > 1 and not argv[1].startswith("-"):
        nested = resolve_command(argv[1], SESSION_COMMANDS)
        if nested is None:
            raise CLIError(f"unknown session command: {argv[1]}")
        return ["session", nested.parser, *argv[2:]], nested.name
    return [command.parser, *argv[1:]], command.name


def add_attach_options(target):
    target.add_argument(
        "--mouse-mode",
        choices=MOUSE_MODES,
        default=argparse.SUPPRESS,
        help="mouse coordinates for this client (default: auto)",
    )
    target.add_argument("--debug", action="store_true", help="enable DEBUG diagnostics")
    target.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="WARNING",
        help="diagnostic log level (default: WARNING)",
    )
    target.add_argument(
        "--log-file", help="diagnostic log file (default: XDG state cosmos/logs/ui.log)"
    )


def add_session_arguments(target, operation):
    if operation == "attach":
        target.add_argument(
            "name", nargs="?", metavar="SESSION", help="session name (default: main)"
        )
        target.add_argument(
            "-s",
            "--session",
            dest="session",
            metavar="SESSION",
            help="session name (default: main)",
        )
        add_attach_options(target)
    elif operation == "new":
        target.add_argument(
            "name", nargs="?", metavar="SESSION", help="new session name"
        )
        target.add_argument(
            "-s",
            "--session",
            dest="session",
            metavar="SESSION",
            help="new session name",
        )
        target.add_argument(
            "-d",
            "--detached",
            action="store_true",
            help="create without opening the UI",
        )
        target.add_argument(
            "-c", "--cwd", metavar="DIR", help="initial working directory"
        )
        add_attach_options(target)
    elif operation == "list":
        target.add_argument(
            "-j", "--json", action="store_true", help="machine-readable output"
        )
    elif operation in ("kill", "exists"):
        description = "destroy" if operation == "kill" else "check"
        target.add_argument(
            "name",
            nargs="?",
            metavar="SESSION",
            help=f"session to {description}",
        )
        target.add_argument(
            "-s",
            "--session",
            dest="session",
            metavar="SESSION",
            help=f"session to {description}",
        )
    elif operation == "rename":
        target.add_argument(
            "names",
            nargs="*",
            metavar="NAME",
            help="OLD NEW, or NEW when -s is used",
        )
        target.add_argument(
            "-s",
            "--session",
            dest="session",
            metavar="SESSION",
            help="current session name",
        )
        target.usage = "%(prog)s [-s OLD] [OLD] NEW"
    elif operation == "history":
        target.add_argument(
            "name", nargs="?", metavar="SESSION", help="session name (default: main)"
        )
        target.add_argument(
            "-s",
            "--session",
            dest="session",
            metavar="SESSION",
            help="session name (default: main)",
        )
        target.add_argument(
            "-p", "--pane", metavar="PANE", help="export only this pane ID, such as %%0"
        )
        target.add_argument(
            "-l",
            "--lines",
            type=positive_integer,
            metavar="N",
            help="last N retained physical lines per pane",
        )
        target.add_argument(
            "-a", "--ansi", action="store_true", help="retain ANSI color escapes"
        )
        target.add_argument(
            "-j", "--json", action="store_true", help="include pane metadata as JSON"
        )
        target.add_argument(
            "-o",
            "--output",
            metavar="PATH",
            help="write UTF-8 output to a file instead of stdout",
        )


def add_management_arguments(target, operation):
    if operation == "agent":
        operations = target.add_subparsers(dest="operation", required=True)
        operations.add_parser(
            "migrate", help="move legacy Cosmos Agent data; close Agent frontends first"
        )
        setup = operations.add_parser(
            "configure", help="configure a direct provider API"
        )
        setup.add_argument("--provider")
        setup.add_argument("--model")
        setup.add_argument("--base-url")
        setup.add_argument(
            "--set-key", action="store_true", help="prompt for the API key without echo"
        )
        export = operations.add_parser(
            "export", help="export an Agent conversation as sanitized JSON"
        )
        export.add_argument("id", help="OpenCode conversation ID (ses_...)")
        export.add_argument(
            "--output", help="new output file; default: private Agent exports directory"
        )
    elif operation == "mod":
        operations = target.add_subparsers(dest="operation")
        operations.add_parser("list", help="list registered Mods")
        operations.add_parser(
            "add", help="register a TOML or JSON manifest"
        ).add_argument("manifest")
        for name in ("start", "stop", "remove"):
            operations.add_parser(name, help=f"{name} a registered Mod").add_argument(
                "id"
            )
    elif operation == "action":
        target.add_argument("id", help="action ID from actions.list")
    elif operation == "rpc":
        target.add_argument("method")
        target.add_argument(
            "params", nargs="?", default="{}", help="JSON object (default: {})"
        )
    elif operation == "open":
        target.add_argument("file")
    elif operation == "completion":
        target.add_argument(
            "shell",
            choices=["bash"],
            help="source with: source <(cosmos completion bash)",
        )
    elif operation == "help":
        target.add_argument("topic", nargs="*")


def parser():
    cli = argparse.ArgumentParser(
        prog="cosmos",
        description="Cosmos persistent terminal workspace",
        epilog="With no command, attach to 'main'. 'cosmos SESSION' attaches to SESSION.\n"
        "Help marks the shortest accepted prefix in brackets, e.g. [a]ttach; longer unique prefixes also work.\n"
        "Environment: COSMOS_BINARY overrides the coordinator; COSMOS_TMUX overrides tmux.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cli.add_argument("--version", action="version", version=DISPLAY_VERSION)
    cli.add_argument(
        "--mouse-mode",
        choices=MOUSE_MODES,
        default=argparse.SUPPRESS,
        help="mouse coordinates for this client (default: auto)",
    )
    commands = cli.add_subparsers(dest="command", metavar="COMMAND")
    parsers = {}
    for spec in SESSION_COMMANDS:
        target = commands.add_parser(
            spec.parser, help=spec.summary, description=spec.summary
        )
        add_session_arguments(target, spec.name)
        parsers[spec.parser] = target
    session_group = commands.add_parser(
        "session",
        help="manage sessions through a command group",
        description="Manage sessions through a command group; commands match the flat forms.",
    )
    parsers["session"] = session_group
    session_commands = session_group.add_subparsers(
        dest="session_command", metavar="COMMAND", required=True
    )
    session_parsers = {}
    for spec in SESSION_COMMANDS:
        target = session_commands.add_parser(
            spec.parser, help=spec.summary, description=spec.summary
        )
        add_session_arguments(target, spec.name)
        session_parsers[spec.parser] = target
    for spec in TOP_LEVEL_COMMANDS:
        if spec.name in {command.name for command in SESSION_COMMANDS}:
            continue
        if spec.name == "session":
            continue
        target = commands.add_parser(
            spec.parser, help=spec.summary, description=spec.summary
        )
        add_management_arguments(target, spec.name)
        parsers[spec.parser] = target
    return cli, parsers, session_parsers


def session_name(target, args, default=None):
    positional = getattr(args, "name", None)
    option = getattr(args, "session", None)
    if positional and option and positional != option:
        target.error("session name given twice")
    name = option or positional or default
    if name is None:
        target.error("session name required")
    return name


def rename_names(target, args):
    if args.session:
        if len(args.names) != 1:
            target.error("usage: cosmos rename [-s OLD] NEW")
        return args.session, args.names[0]
    if len(args.names) != 2:
        target.error("usage: cosmos rename OLD NEW")
    return args.names[0], args.names[1]


def print_help(cli, commands, session_commands, topic):
    if not topic:
        cli.print_help()
        return
    if topic[0] == "session":
        if len(topic) == 1:
            commands["session"].print_help()
            return
        spec = resolve_command(topic[1], SESSION_COMMANDS)
        if spec is None:
            cli.exit(1, f"cosmos: unknown help topic: {' '.join(topic)}\n")
        session_commands[spec.parser].print_help()
        return
    spec = resolve_command(topic[0], TOP_LEVEL_COMMANDS)
    if spec is None:
        cli.exit(1, f"cosmos: unknown help topic: {' '.join(topic)}\n")
    commands[spec.parser].print_help()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cli, commands, session_commands = parser()
    mouse_option = []
    if argv and argv[0].startswith("--mouse-mode="):
        mouse_option = [argv.pop(0)]
    elif len(argv) > 1 and argv[0] == "--mouse-mode":
        mouse_option = argv[:2]
        del argv[:2]
    original = list(argv)
    try:
        parser_argv, operation = canonicalize(argv)
    except CLIError as error:
        cli.exit(1, f"cosmos: {error}\n")
    args = cli.parse_args(mouse_option + parser_argv)
    if args.command == "[he]lp":
        try:
            print_help(cli, commands, session_commands, args.topic)
        except CLIError as error:
            cli.exit(1, f"cosmos: {error}\n")
        return 0
    if args.command == "[com]pletion":
        print((PROJECT_ROOT / "shell/completions/cosmos.bash").read_text(), end="")
        return 0
    try:
        if args.command == "session":
            operation = PARSER_NAMES[args.session_command]
            target = session_commands[args.session_command]
        else:
            operation = PARSER_NAMES[args.command]
            target = commands[args.command]
        if operation == "agent":
            if args.operation == "migrate":
                from cosmos_tui.features.agent.migration import migrate

                moved = migrate()
                print(
                    "\n".join(moved) if moved else "No legacy Cosmos Agent data found"
                )
            elif args.operation == "configure":
                from cosmos_tui.features.agent.profile import configure

                provider, model = configure(
                    args.provider, args.model, args.base_url, args.set_key
                )
                print(f"Cosmos Agent provider: {provider}; model: {model}")
            else:
                from cosmos_tui.features.agent.conversations import export_conversation

                print(export_conversation(args.id, args.output))
            return 0
        if operation == "new":
            from cosmos_tui.terminal import sessions

            name = session_name(target, args)
            asyncio.run(sessions.create(name, args.cwd))
            if args.detached:
                print(name)
                return 0
            args.session = name
            from cosmos_tui.runtime.bootstrap import run

            run(args)
            return 0
        if operation == "list":
            from cosmos_tui.terminal import sessions

            rows = asyncio.run(sessions.listing())
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for row in rows:
                    print(f"{row['id']}\t{row['name']}\t{row['windows']} window(s)")
            return 0
        if operation == "exists":
            from cosmos_tui.terminal import sessions

            return 0 if asyncio.run(sessions.exists(session_name(target, args))) else 1
        if operation == "kill":
            from cosmos_tui.terminal import sessions

            asyncio.run(sessions.kill(session_name(target, args)))
            return 0
        if operation == "rename":
            from cosmos_tui.terminal import sessions

            old, new = rename_names(target, args)
            asyncio.run(sessions.rename(old, new))
            return 0
        if operation == "history":
            from cosmos_tui.terminal import sessions

            name = session_name(target, args, default="main")
            rows = asyncio.run(sessions.history(name, args.pane, args.lines, args.ansi))
            output = sessions.format_history(rows, args.json)
            if args.output:
                Path(args.output).expanduser().write_text(output, encoding="utf-8")
            else:
                print(output, end="")
            return 0
        if operation == "attach":
            args.session = session_name(target, args, default="main")
            from cosmos_tui.runtime.bootstrap import run

            run(args)
            return 0
        if operation == "cache-clear":
            from cosmos_tui.features.reader.disk import DiskCache

            DiskCache().clear()
            print(
                "Reader disk cache cleared; active clients retain their memory caches"
            )
            return 0
        if operation == "stop":
            from cosmos_tui.core import rpc

            asyncio.run(rpc.call("daemon.shutdown", {}))
            from cosmos_tui.features.agent.monitor.service import suspend

            suspend(os.getenv("COSMOS_TMUX_SOCKET", "cosmos"))
            print("Cosmos is stopping · terminal sessions retained")
            return 0
        if operation == "open" and Path(args.file).expanduser().is_dir():
            from cosmos_tui.features.files.opener import open_directory

            open_directory(args.file)
            return 0
        binary = Path(
            os.environ.get("COSMOS_BINARY", PROJECT_ROOT / "target/release/cosmos")
        )
        raise SystemExit(subprocess.call([str(binary), operation, *original[1:]]))
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        cli.exit(1, f"cosmos: {error}\n")
        return 1
