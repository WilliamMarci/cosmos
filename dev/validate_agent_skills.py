"""Manual native-registry validation with temporary fixtures; no model calls.

Run from the Cosmos root with PYTHONPATH=python:terminal_agent.
"""

import asyncio
import base64
import json
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from cosmos_tui.features.agent.launch import configuration
from cosmos_tui.core.paths import PROJECT_ROOT


async def main():
    with tempfile.TemporaryDirectory(prefix="cosmos-skills-") as d:
        root = Path(d)
        project = root / "project"
        project.mkdir()
        env = dict(
            os.environ,
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_CACHE_HOME=str(root / "cache"),
            OPENCODE_DISABLE_MODELS_FETCH="1",
            OPENCODE_PASSWORD="cosmos-skill-test",
            OPENCODE_CONFIG_PROJECT_DISABLE="1",
        )
        old = Path.cwd()
        os.chdir(project)
        try:
            before = dict(os.environ)
            os.environ.update(env)
            try:
                config = configuration("cosmos-skill-test", "%0")
            finally:
                os.environ.clear()
                os.environ.update(before)
        finally:
            os.chdir(old)
        learned = project / ".cosmos/skills/vim-task"
        learned.mkdir(parents=True)
        (learned / "SKILL.md").write_text(
            "---\nname: vim-task\ndescription: Edit a fixture in Vim.\n---\nRead the current screen before acting.\n"
        )
        personal = root / "config/cosmos/skills/personal-task"
        personal.mkdir(parents=True)
        (personal / "SKILL.md").write_text(
            "---\nname: personal-task\ndescription: Reuse a personal workflow.\n---\nInspect the current screen.\n"
        )
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        bun = str(PROJECT_ROOT / ".build/agent-runtime/node_modules/.bin/bun")
        log = (root / "server.log").open("wb")
        p = await asyncio.create_subprocess_exec(
            bun,
            "run",
            "src/index.ts",
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
            ready = await asyncio.wait_for(p.stdout.readline(), 30)
            assert ready, (root / "server.log").read_text()
            url = json.loads(ready)["url"]
            headers = {
                "Authorization": "Basic "
                + base64.b64encode(b"opencode:cosmos-skill-test").decode()
            }

            def get(route):
                req = Request(
                    url
                    + route
                    + "?"
                    + urlencode({"location[directory]": str(project)}),
                    headers=headers,
                )
                with urlopen(req, timeout=30) as r:
                    return json.load(r)

            await asyncio.to_thread(get, "/api/config")
            skills = {}
            for _ in range(30):
                skills = await asyncio.to_thread(get, "/api/skill")
                if {
                    "cosmos-tui",
                    "cosmos-skill-export",
                    "vim-task",
                    "personal-task",
                } <= {s["name"] for s in skills["data"]}:
                    break
                await asyncio.sleep(0.2)
            commands = await asyncio.to_thread(get, "/api/command")
            names = {s["name"] for s in skills["data"]}
            assert {
                "cosmos-tui",
                "cosmos-skill-export",
                "vim-task",
                "personal-task",
            } <= names
            assert "cosmos-export-skill" in {c["name"] for c in commands["data"]}
            print("Skills:", ", ".join(sorted(names)))
            print("Commands:", ", ".join(c["name"] for c in commands["data"]))
            print(
                "PASS: actual OpenCode discovers bundled + learned project skills and export command"
            )
        finally:
            p.stdin.close()
            try:
                await asyncio.wait_for(p.wait(), 5)
            except asyncio.TimeoutError:
                p.kill()
                await p.wait()
            log.close()


if __name__ == "__main__":
    asyncio.run(main())
