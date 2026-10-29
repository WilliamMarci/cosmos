"""Check real skill/MCP/command discovery and exclusion of foreign config.

Run with PYTHONPATH=python:terminal_agent; --system checks installed OpenCode.
All fixtures and the private server use temporary directories; no model calls.
"""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.features.agent.launch import environment


def skill(directory, name):
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Isolated fixture workflow.\n---\nInspect the screen.\n"
    )


async def main(system=False):
    with tempfile.TemporaryDirectory(prefix="cosmos-agent-scope-") as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        user_home = root / "user-home"
        user_home.mkdir()
        sentinel = root / "foreign-mcp-was-started"
        foreign = {
            "mcp": {
                "servers": {
                    "foreign-mcp": {
                        "type": "local",
                        "command": [
                            sys.executable,
                            "-c",
                            f"from pathlib import Path; Path({str(sentinel)!r}).touch()",
                        ],
                    }
                }
            },
            "commands": {"foreign-command": {"template": "Do not load this."}},
        }
        for file in (
            root / "config/opencode/opencode.json",
            project / ".opencode/opencode.json",
            project / "opencode.json",
        ):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(foreign))
        for directory, name in (
            (user_home / ".agents/skills/foreign-home", "foreign-home"),
            (user_home / ".claude/skills/foreign-claude", "foreign-claude"),
            (project / ".agents/skills/foreign-project", "foreign-project"),
            (root / "foreign-env", "foreign-env"),
            (project / ".cosmos/skills/vim-task", "vim-task"),
            (root / "config/cosmos/skills/personal-task", "personal-task"),
        ):
            skill(directory, name)
        original_cwd = Path.cwd()
        try:
            os.chdir(project)
            with patch.dict(
                os.environ,
                HOME=str(user_home),
                XDG_CONFIG_HOME=str(root / "config"),
                XDG_DATA_HOME=str(root / "data"),
                XDG_STATE_HOME=str(root / "state"),
                XDG_CACHE_HOME=str(root / "cache"),
                OPENCODE_CONFIG_CONTENT=json.dumps(
                    dict(foreign, skills=[str(root / "foreign-env")])
                ),
                OPENCODE_CONFIG=str(project / "opencode.json"),
            ):
                env = environment("cosmos-skill-test", "%0")
        finally:
            os.chdir(original_cwd)
        config_file = Path(env["OPENCODE_CONFIG"])
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {"commands": {"cosmos-custom": {"template": "Cosmos-owned command"}}}
            )
        )
        env.update(
            OPENCODE_DISABLE_MODELS_FETCH="1", OPENCODE_PASSWORD="cosmos-skill-test"
        )
        command = (
            [shutil.which("opencode")]
            if system
            else [
                str(PROJECT_ROOT / ".build/agent-runtime/node_modules/.bin/bun"),
                "run",
                "src/index.ts",
            ]
        )
        with (root / "server.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                *command,
                "serve",
                "--stdio",
                "--port",
                "0",
                cwd=PROJECT_ROOT / "vendor/opencode/packages/cli",
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=log,
            )
            try:
                ready = await asyncio.wait_for(process.stdout.readline(), 30)
                assert ready, (root / "server.log").read_text()
                url = json.loads(ready)["url"]
                headers = {
                    "Authorization": "Basic "
                    + base64.b64encode(b"opencode:cosmos-skill-test").decode()
                }

                def get(route):
                    request = Request(
                        url
                        + route
                        + "?"
                        + urlencode({"location[directory]": str(project)}),
                        headers=headers,
                    )
                    with urlopen(request, timeout=30) as response:
                        return json.load(response)

                await asyncio.to_thread(get, "/api/config")
                expected = {
                    "cosmos-tui",
                    "cosmos-skill-export",
                    "vim-task",
                    "personal-task",
                }
                for _ in range(40):
                    names = {
                        item["name"]
                        for item in (await asyncio.to_thread(get, "/api/skill"))["data"]
                    }
                    if expected <= names:
                        break
                    await asyncio.sleep(0.2)
                commands = {
                    item["name"]
                    for item in (await asyncio.to_thread(get, "/api/command"))["data"]
                }
                mcps = await asyncio.to_thread(get, "/api/mcp")
                assert expected <= names, names
                assert not any(name.startswith("foreign-") for name in names | commands)
                assert "foreign-mcp" not in json.dumps(mcps), mcps
                assert "cosmos_actions" in json.dumps(mcps), mcps
                assert not sentinel.exists(), "foreign MCP was executed"
                assert {"cosmos-export-skill", "cosmos-custom"} <= commands, commands
                assert env["HOME"] == str(user_home), "shell HOME must remain intact"
                print("Skills:", ", ".join(sorted(names)))
                print("Commands:", ", ".join(sorted(commands)))
                print(
                    "PASS: Cosmos libraries/config work; foreign skills, MCPs and commands excluded"
                )
            finally:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", action="store_true")
    asyncio.run(main(parser.parse_args().system))
