"""Isolated real-Tmux acceptance for the public session CLI."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    os.getenv("COSMOS_TEST_TMUX"), "set COSMOS_TEST_TMUX=1 for isolated Tmux tests"
)
class SessionCLITests(unittest.TestCase):
    def test_create_list_and_export_all_panes(self):
        with tempfile.TemporaryDirectory(prefix="cosmos-session-test-") as directory:
            env = dict(
                os.environ, HOME=directory, COSMOS_TMUX_SOCKET=Path(directory).name
            )

            def run(*args, check=True):
                return subprocess.run(
                    [str(ROOT / "cosmos"), *args],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=check,
                )

            def tmux(*args):
                return subprocess.check_output(
                    [
                        env.get("COSMOS_TMUX", "tmux"),
                        "-L",
                        env["COSMOS_TMUX_SOCKET"],
                        *args,
                    ],
                    env=env,
                    text=True,
                )

            try:
                self.assertEqual(json.loads(run("sessions", "--json").stdout), [])
                run("session", "new", "alpha", "-d", "--cwd", directory)
                self.assertNotEqual(
                    run("new", "alpha", "-d", check=False).returncode, 0
                )
                pane = tmux(
                    "display-message", "-p", "-t", "alpha:", "#{pane_id}"
                ).strip()
                tmux(
                    "send-keys",
                    "-t",
                    pane,
                    "printf 'SESSION-HISTORY-PROOF\\n'",
                    "Enter",
                )
                second = tmux(
                    "split-window", "-d", "-P", "-F", "#{pane_id}", "-t", pane
                ).strip()
                for _ in range(50):
                    data = json.loads(run("history", "alpha", "--json").stdout)
                    if any("SESSION-HISTORY-PROOF\n" in row["text"] for row in data):
                        break
                    time.sleep(0.05)
                self.assertEqual(len(data), 2)
                self.assertIn(
                    "SESSION-HISTORY-PROOF\n",
                    next(r["text"] for r in data if r["pane"] == pane),
                )
                destination = Path(directory) / "history.txt"
                run(
                    "session",
                    "history",
                    "alpha",
                    "--pane",
                    pane,
                    "--lines",
                    "3",
                    "-o",
                    str(destination),
                )
                self.assertLessEqual(len(destination.read_text().splitlines()), 3)
                run("new", "beta", "-d")
                self.assertNotEqual(
                    run("history", "beta", "--pane", second, check=False).returncode, 0
                )
                self.assertEqual(
                    {
                        s["name"]
                        for s in json.loads(run("session", "list", "--json").stdout)
                    },
                    {"alpha", "beta"},
                )
            finally:
                subprocess.run(
                    [
                        env.get("COSMOS_TMUX", "tmux"),
                        "-L",
                        env["COSMOS_TMUX_SOCKET"],
                        "kill-server",
                    ],
                    env=env,
                    capture_output=True,
                )


if __name__ == "__main__":
    unittest.main()
