"""Manual real-terminal check; run from the Cosmos root with PYTHONPATH=python.

Uses an isolated Tmux service and XDG directories, without model calls.
"""

import asyncio
import shlex
import tempfile
import uuid
from pathlib import Path
from cosmos_tui.features.agent.terminal import TerminalTools
from cosmos_tui.features.agent.launch import arguments


async def main():
    with tempfile.TemporaryDirectory(prefix="cosmos-agent-ui-") as d:
        socket = "cosmos-agent-ui-" + uuid.uuid4().hex
        t = TerminalTools(socket)
        try:
            await t.backend.cli(
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-x",
                "100",
                "-y",
                "35",
                "-s",
                "test",
                "bash --noprofile --norc",
            )
            pane = (await t.panes())[0]["pane_id"]
            env = {
                "XDG_DATA_HOME": d + "/data",
                "XDG_STATE_HOME": d + "/state",
                "XDG_CACHE_HOME": d + "/cache",
                "XDG_CONFIG_HOME": d + "/config",
                "OPENCODE_DISABLE_MODELS_FETCH": "1",
                "PYTHONPATH": str(Path.cwd() / "python"),
            }
            cmd = [
                "env",
                *(k + "=" + v for k, v in env.items()),
                *arguments(t.backend, pane),
            ]
            agent = (
                await t.backend.cli(
                    "new-window",
                    "-d",
                    "-P",
                    "-F",
                    "#{pane_id}",
                    "-c",
                    d,
                    shlex.join(cmd),
                )
            ).strip()
            last = ""
            for i in range(120):
                await asyncio.sleep(0.25)
                try:
                    last = await t.backend.cli("capture-pane", "-p", "-t", agent)
                except RuntimeError:
                    break
                if "powered by opencode" in last:
                    assert (
                        await t.backend.cli(
                            "show-options", "-pqv", "-t", agent, "@cosmos_agent"
                        )
                    ).strip() == "1"
                    print(last)
                    print("PASS: branded Cosmos Agent rendered in a real Tmux terminal")
                    return
            print(last)
            raise RuntimeError("Agent UI did not display Cosmos branding")
        finally:
            await t.backend.cli("kill-server")


asyncio.run(main())
