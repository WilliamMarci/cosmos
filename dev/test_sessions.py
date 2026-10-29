"""Isolated real-Tmux acceptance for the public session CLI."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "python")]

from cosmos_tui.terminal.tmux import Tmux  # noqa: E402


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


    def test_exact_names_and_flat_forms(self):
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

            try:
                run("new", "-s", "alpha2", "-d")
                self.assertEqual(run("ex", "alpha", check=False).returncode, 1)
                self.assertEqual(run("exists", "alpha2").returncode, 0)
                run("n", "-s", "alpha", "-d")
                self.assertEqual(run("exi", "alpha").returncode, 0)
                names = {
                    row["name"] for row in json.loads(run("ls", "--json").stdout)
                }
                self.assertEqual(names, {"alpha", "alpha2"})
                run("rename", "-s", "alpha", "beta")
                self.assertEqual(run("ex", "alpha", check=False).returncode, 1)
                self.assertEqual(run("ex", "beta").returncode, 0)
                self.assertIn("beta", run("hi", "beta", "--json").stdout)
                run("k", "beta")
                self.assertEqual(run("ex", "beta", check=False).returncode, 1)
                run("rename", "alpha2", "gamma")
                self.assertEqual(run("list").stdout.splitlines(), ["gamma\t1 window(s)"])
                run("k", "gamma")
                self.assertEqual(run("list").stdout, "")
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


@unittest.skipUnless(
    os.getenv("COSMOS_TEST_TMUX"), "set COSMOS_TEST_TMUX=1 for isolated Tmux tests"
)
class ConnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_creates_an_exact_session_without_prefix_match(self):
        with tempfile.TemporaryDirectory(prefix="cosmos-connect-test-") as directory:
            socket = Path(directory).name
            env = dict(
                os.environ, HOME=directory, COSMOS_TMUX_SOCKET=socket
            )
            with patch.dict(os.environ, env, clear=False):
                def tmux(*args):
                    return subprocess.run(
                        ["tmux", "-L", socket, *args],
                        env=env,
                        text=True,
                        capture_output=True,
                    )

                try:
                    self.assertEqual(
                        tmux("-f", "/dev/null", "new-session", "-d", "-s", "alpha2")
                        .returncode,
                        0,
                    )
                    backend = Tmux("alpha")
                    self.assertTrue(await backend.connect())
                    self.assertTrue((backend.session_id or "").startswith("$"))
                    self.assertEqual(
                        tmux("display-message", "-p", "-t", backend.session_id, "#{pane_current_path}").stdout.strip(),
                        directory,
                    )
                    self.assertEqual(
                        tmux("has-session", "-t", "=alpha").returncode, 0
                    )
                    self.assertEqual(
                        tmux("has-session", "-t", "=alpha2").returncode, 0
                    )
                    await backend.close()
                    second = Tmux("alpha")
                    self.assertFalse(await second.connect())
                    await second.close()
                finally:
                    tmux("kill-server")


if __name__ == "__main__":
    unittest.main()
