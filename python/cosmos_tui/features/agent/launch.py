"""Launch the Cosmos-branded OpenCode frontend with a private terminal bridge."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

from cosmos_tui.core.paths import PROJECT_ROOT, config_home


def arguments(backend, source_pane, prompt=""):
    runtime()
    args = [
        sys.executable,
        "-m",
        "cosmos_tui.features.agent",
        "launch",
        "--socket",
        backend.argv[2],
        "--source-pane",
        source_pane,
    ]
    if prompt:
        args += ["--prompt", prompt]
    return args


def configuration(socket, source_pane):
    from cosmos_tui.features.agent.skills import commands, personal_skills, skill_paths

    return {
        "skills": skill_paths(),
        "commands": commands(),
        "default_agent": "cosmos",
        "agents": {
            "cosmos": {
                "mode": "primary",
                "description": "Cosmos terminal workspace agent",
                "system": (PROJECT_ROOT / "config/cosmos-agent-prompt.md").read_text()
                + f"\nSource pane: {source_pane}. Cosmos Tmux service: {socket}.\n"
                + f"Personal Cosmos skill library: {personal_skills()}.\n"
                + f"Skill export helper Python: {sys.executable}.\n",
            }
        },
        "mcp": {
            "servers": {
                "cosmos_terminal": {
                    "type": "local",
                    "codemode": False,
                    "command": [
                        sys.executable,
                        "-m",
                        "cosmos_tui.features.agent",
                        "mcp",
                        "--socket",
                        socket,
                    ],
                    "environment": {"PYTHONPATH": str(PROJECT_ROOT / "python")},
                },
                "cosmos_actions": {
                    "type": "local",
                    "codemode": False,
                    "command": [
                        sys.executable,
                        "-m",
                        "cosmos_tui.features.agent",
                        "mcp",
                        "--socket",
                        socket,
                        "--toolset",
                        "actions",
                    ],
                    "environment": {"PYTHONPATH": str(PROJECT_ROOT / "python")},
                },
            }
        },
        "permissions": [
            {"action": "cosmos_actions_*", "resource": "*", "effect": "ask"},
            {
                "action": "cosmos_actions_list_actions",
                "resource": "*",
                "effect": "allow",
            },
            {"action": "cosmos_terminal_*", "resource": "*", "effect": "ask"},
            {
                "action": "cosmos_terminal_list_panes",
                "resource": "*",
                "effect": "allow",
            },
            {
                "action": "cosmos_terminal_read_screen",
                "resource": "*",
                "effect": "allow",
            },
        ],
    }


def runtime():
    mode = os.getenv("COSMOS_AGENT_RUNTIME", "auto")
    if mode not in ("auto", "bundled", "source", "system"):
        raise ValueError("COSMOS_AGENT_RUNTIME must be auto, bundled, source or system")
    if mode == "auto" and os.getenv("COSMOS_OPENCODE"):
        mode = "system"
    binary = PROJECT_ROOT / "bin/cosmos-agent"
    if mode == "bundled" or (mode == "auto" and binary.is_file()):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError("Bundled Cosmos Agent is unavailable")
        return [str(binary)], None
    root = PROJECT_ROOT / "vendor/opencode"
    bun = shutil.which("bun") or str(
        PROJECT_ROOT / ".build/agent-runtime/node_modules/.bin/bun"
    )
    source_ready = (
        Path(bun).is_file()
        and (root / "node_modules").is_dir()
        and (root / "packages/tui/src/component/cosmos-logo.tsx").is_file()
    )
    if mode == "source" or (mode == "auto" and source_ready):
        if not source_ready:
            raise RuntimeError(
                "Cosmos Agent development runtime is missing; run dev/setup_agent.sh"
            )
        return [bun, "run", "src/index.ts"], root / "packages/cli"
    executable = shutil.which(os.getenv("COSMOS_OPENCODE", "opencode"))
    if not executable:
        raise RuntimeError("OpenCode not found; install it or run dev/setup_agent.sh")
    return [executable], None


def environment(socket, source_pane):
    # Capture Cosmos paths before redirecting OpenCode's XDG bases. Never
    # import an inherited OpenCode overlay, plugins, MCPs or discovery flags.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("OPENCODE_")
    }
    root = config_home() / "cosmos/agent"
    home = Path.home()
    env.update(
        COSMOS_AGENT="1",
        OPENCODE_CONFIG_DIR=str(root),
        OPENCODE_CONFIG=str(root / "opencode.json"),
        OPENCODE_CONFIG_CONTENT=json.dumps(configuration(socket, source_pane)),
        OPENCODE_CONFIG_PROJECT_DISABLE="1",
        OPENCODE_DISABLE_CLAUDE_CODE="1",
        # Stock OpenCode 2.1.2 exposes this discovery-home override. It fences
        # ~/.agents without changing HOME seen by terminal applications.
        OPENCODE_TEST_HOME=str(root / "home"),
        OPENCODE_DISABLE_AUTOUPDATE="1",
    )
    for variable, default in (
        ("XDG_CONFIG_HOME", home / ".config"),
        ("XDG_DATA_HOME", home / ".local/share"),
        ("XDG_CACHE_HOME", home / ".cache"),
        ("XDG_STATE_HOME", home / ".local/state"),
    ):
        env[variable] = str(Path(os.environ.get(variable) or default) / "cosmos/agent")
    return env


def launch(socket, source_pane, prompt=""):
    executable, workdir = runtime()
    env = environment(socket, source_pane)
    env["PATH"] = str(Path(executable[0]).parent) + os.pathsep + env.get("PATH", "")
    current = os.environ.get("TMUX_PANE")
    if current:
        from cosmos_tui.features.agent.terminal import TerminalTools

        tools = TerminalTools(socket)
        asyncio.run(
            tools.backend.cli("set-option", "-p", "-t", current, "@cosmos_agent", "1")
        )
    directory = os.getcwd()
    command = executable + ["--standalone", directory]
    if prompt:
        command += ["--prompt", prompt]
    if workdir:
        os.chdir(workdir)
    os.execvpe(executable[0], command, env)
