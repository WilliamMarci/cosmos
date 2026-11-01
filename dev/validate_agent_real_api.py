"""Opt-in paid DeepSeek smoke test, isolated from live panes and saved grants."""

import argparse
import fcntl
import time
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from unittest.mock import patch

from cosmos_tui.features.agent.profile import load_profile, initialize_profile
from cosmos_tui.features.agent.launch import environment, runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real-api",
        action="store_true",
        help="Explicitly authorize a real, billed DeepSeek request",
    )
    args = parser.parse_args()
    if not args.real_api:
        parser.error("--real-api is required; this probe uses a real provider")
    settings, credentials = load_profile()
    if settings["provider"] != "deepseek" or not credentials.get("deepseek"):
        raise RuntimeError(
            "Configured DeepSeek credentials are required (values are never printed)"
        )
    key = credentials["deepseek"]
    socket = "cosmos-real-api-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="cosmos-real-api-") as directory:
        base = Path(directory)
        project = base / "workspace"
        project.mkdir()
        (project / "sample.txt").write_text(
            "COSMOS_NATIVE_READ_OK\nprocess p p > z z\n"
        )
        subprocess.run(
            [
                "tmux",
                "-L",
                socket,
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-x",
                "90",
                "-y",
                "24",
                "-s",
                "api-fixture",
                "-c",
                str(project),
                "/bin/bash --noprofile --norc",
            ],
            check=True,
            capture_output=True,
        )
        env = {}
        try:
            pane = subprocess.check_output(
                ["tmux", "-L", socket, "list-panes", "-F", "#{pane_id}"], text=True
            ).strip()
            with patch.dict(
                os.environ,
                XDG_CONFIG_HOME=str(base / "config"),
                XDG_RUNTIME_DIR=str(base / "runtime"),
                COSMOS_TASKS_HOME=str(base / "tasks"),
                COSMOS_AGENT_RUNTIME="source",
            ):
                (base / "runtime").mkdir(mode=0o700)
                profile = initialize_profile()
                (profile / "profile.json").write_text(json.dumps(settings))
                (profile / "credentials.json").write_text(json.dumps({"deepseek": key}))
                (profile / "credentials.json").chmod(0o600)
                env = environment(socket, pane)
                env["OPENCODE_DISABLE_MODELS_FETCH"] = "1"
                cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
                cfg["agents"]["cosmos"]["steps"] = 10
                cfg["permissions"] += [
                    dict(action=name, resource="*", effect="allow")
                    for name in [
                        "read",
                        "glob",
                        "grep",
                        "external_directory",
                        "cosmos_terminal_acquire_control",
                    ]
                ]
                cfg["permissions"] += [
                    dict(action=name, resource="*", effect="deny")
                    for name in ["shell", "edit", "write", "patch"]
                ]
                env["OPENCODE_CONFIG_CONTENT"] = json.dumps(cfg)
                command, runtime_cwd = runtime()
                prompt = (
                    f"This is an authorized bounded API integration test in a disposable fixture. Use only target {pane}. "
                    f'Call cosmos_context(target="{pane}") and cosmos_observe(target="{pane}", layers=["text"]). '
                    f"Use native read to read {project / 'sample.txt'}, native glob to find *.txt with path={project}, and native grep to search COSMOS_NATIVE_READ_OK with path={project} (do not use Shell). "
                    f'Use cosmos_task begin on {pane} with a fresh observation, then cosmos_step text="printf COSMOS_REAL_TOOL_OK" with submit=true. '
                    "Verify the marker in result/context, then cosmos_task release. No other terminal input or filesystem writes. "
                    "Finally answer REAL_API_TOOLS_VERIFIED plus the names of successfully used tools. Do not explore source code or install anything."
                )
                completed = subprocess.run(
                    command
                    + [
                        "run",
                        "--standalone",
                        "--format",
                        "json",
                        "--title",
                        "Disposable DeepSeek tool probe",
                        prompt,
                    ],
                    cwd=runtime_cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if key in completed.stdout or key in completed.stderr:
                    raise RuntimeError(
                        "Credential appeared in subprocess output; output withheld"
                    )
                events = []
                for line in completed.stdout.splitlines():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                calls = [
                    e.get("part", {}) for e in events if e.get("type") == "tool_use"
                ]
                tools = [
                    dict(tool=c.get("tool"), status=c.get("state", {}).get("status"))
                    for c in calls
                ]
                required = {
                    "cosmos_context",
                    "cosmos_observe",
                    "cosmos_task",
                    "cosmos_step",
                    "read",
                    "glob",
                    "grep",
                }
                actual = {r["tool"] for r in tools if r["status"] == "completed"}
                screen = subprocess.check_output(
                    ["tmux", "-L", socket, "capture-pane", "-p", "-t", pane], text=True
                )
                terminal_marker = "COSMOS_REAL_TOOL_OK" in screen
                native_read_marker = any(
                    c.get("tool") == "read" and "COSMOS_NATIVE_READ_OK" in json.dumps(c)
                    for c in calls
                )
                costs = [
                    e.get("part", {}).get("cost")
                    for e in events
                    if e.get("type") == "step_finish"
                ]
                report = dict(
                    provider="deepseek",
                    model=settings["model"],
                    exit_code=completed.returncode,
                    tools=tools,
                    missing=sorted(required - actual),
                    final_marker="REAL_API_TOOLS_VERIFIED" in completed.stdout,
                    terminal_marker=terminal_marker,
                    native_read_marker=native_read_marker,
                    reported_cost=sum(c for c in costs if isinstance(c, (int, float)))
                    if costs
                    else None,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2))
                if (
                    completed.returncode
                    or required - actual
                    or not report["final_marker"]
                    or not terminal_marker
                    or not native_read_marker
                ):
                    # Fixture output only, after explicitly checking the configured credential.
                    print(
                        "Diagnostic:",
                        (completed.stderr[-1500:] + completed.stdout[-3000:]).replace(
                            key, "[REDACTED]"
                        ),
                    )
                    raise SystemExit(1)
        finally:
            database = env.get("COSMOS_AGENT_TASK_DB")
            if database and Path(database).parent.exists():
                Path(database).with_suffix(".suspended").touch(mode=0o600)
                lock_path = Path(database + ".worker")
                if lock_path.exists():
                    with lock_path.open("r") as lock:
                        for _ in range(40):
                            try:
                                fcntl.flock(
                                    lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                                )
                                break
                            except BlockingIOError:
                                time.sleep(0.1)
            subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


if __name__ == "__main__":
    main()
