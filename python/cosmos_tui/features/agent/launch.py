"""Launch native Cosmos Agent or an unmodified system OpenCode process."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import secrets
import sys

from cosmos_tui.core.paths import PROJECT_ROOT, python_command
from cosmos_tui.core.hints import unavailable
from cosmos_tui.features.agent.configuration import configuration
from cosmos_tui.features.agent.profile import (
    initialize_profile,
    load_profile,
    profile_root,
)


def arguments(backend, source_pane, prompt=""):
    executable, workdir = runtime()
    if not native_runtime(executable, workdir):
        return executable + (["--prompt", prompt] if prompt else [])
    args = python_command(
        "-m",
        "cosmos_tui.features.agent",
        "launch",
        "--socket",
        backend.argv[2],
        "--source-pane",
        source_pane,
    )
    if prompt:
        args += ["--prompt", prompt]
    return args


def runtime():
    mode = os.getenv("COSMOS_AGENT_RUNTIME", "auto")
    if mode not in ("auto", "bundled", "source", "system"):
        raise ValueError("COSMOS_AGENT_RUNTIME must be auto, bundled, source or system")
    if mode == "auto" and os.getenv("COSMOS_OPENCODE"):
        mode = "system"
    binary = PROJECT_ROOT / "bin/cosmos-agent"
    if mode == "bundled" or (mode == "auto" and binary.is_file()):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError(unavailable("Bundled Cosmos Agent"))
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
            raise RuntimeError(unavailable("Cosmos Agent source runtime"))
        return [bun, "run", "src/index.ts"], root / "packages/cli"
    executable = shutil.which(os.getenv("COSMOS_OPENCODE") or "opencode")
    if not executable:
        raise RuntimeError(
            unavailable("Cosmos Agent runtime (bundled, source or system OpenCode)")
        )
    return [executable], None


def native_runtime(command, workdir):
    mode = os.getenv("COSMOS_AGENT_RUNTIME", "auto")
    if mode == "system" or (mode == "auto" and os.getenv("COSMOS_OPENCODE")):
        return False
    return workdir is not None or Path(command[0]) == PROJECT_ROOT / "bin/cosmos-agent"


def environment(socket, source_pane):
    # Capture Cosmos paths before redirecting OpenCode's XDG bases. Never
    # import an inherited OpenCode overlay, plugins, MCPs or discovery flags.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("OPENCODE_")
    }
    from cosmos_tui.features.agent.binding import launch_binding

    env.pop("COSMOS_WORKSPACE_BINDING", None)
    binding = launch_binding(socket)
    if binding:
        env["COSMOS_WORKSPACE_BINDING"] = binding
    root = profile_root()
    from cosmos_tui.features.agent.tasks.storage import Tasks
    from cosmos_tui.features.agent.tasks.runtime import registry

    task_store = Tasks(socket)
    task_store.settings()
    settings, keys = load_profile()
    env.pop("COSMOS_AGENT_API_KEY", None)
    if keys.get(settings["provider"]):
        env["COSMOS_AGENT_API_KEY"] = keys[settings["provider"]]
    env.update(
        COSMOS_AGENT="1",
        COSMOS_AGENT_SOURCE_PANE=source_pane,
        COSMOS_TASKS_HOME=str(task_store.path.parent),
        COSMOS_AGENT_TASK_DB=str(task_store.path),
        COSMOS_AGENT_TASK_DIR=str(registry(socket)),
        COSMOS_AGENT_CONTEXT_KEY=secrets.token_hex(32),
        COSMOS_AGENT_PROFILE=str(root),
        OPENCODE_CONFIG_DIR=str(root),
        OPENCODE_CONFIG=str(root / "opencode.json"),
        OPENCODE_CONFIG_CONTENT=json.dumps(configuration(socket, source_pane)),
        OPENCODE_CONFIG_PROJECT_DISABLE="1",
        OPENCODE_DISABLE_CLAUDE_CODE="1",
        # Stock OpenCode 2.1.2 exposes this discovery-home override. It fences
        # ~/.agents without changing HOME seen by terminal applications.
        OPENCODE_TEST_HOME=str(root / "home"),
        OPENCODE_DISABLE_AUTOUPDATE="1",
        OPENCODE_DISABLE_FREE_MODELS="1",
    )
    for variable, subdir in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_STATE_HOME", "state"),
    ):
        env[variable] = str(root / subdir)
    env["TMPDIR"] = str(root / "tmp")
    # The standalone TUI talks to its own loopback HTTP server. Keep external
    # provider proxies, but never send private server traffic through them.
    bypass = [value.strip() for key in ("NO_PROXY", "no_proxy") for value in env.get(key, "").split(",") if value.strip()]
    bypass.extend(("localhost", "127.0.0.1", "::1"))
    env["NO_PROXY"] = env["no_proxy"] = ",".join(dict.fromkeys(bypass))
    return env


def launch(socket, source_pane, prompt=""):
    executable, workdir = runtime()
    if not native_runtime(executable, workdir):
        command = executable + (["--prompt", prompt] if prompt else [])
        os.execvp(executable[0], command)
        return
    os.umask(0o077)
    root = initialize_profile()
    from cosmos_tui.features.agent.profile import private_directory

    private_directory(root / "tmp")
    from cosmos_tui.features.agent.theme import install_theme

    install_theme()
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
