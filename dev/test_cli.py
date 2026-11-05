"""Public entry works through symlinks, without starting services for help."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "python")]

from cosmos_tui.core.cli import (  # noqa: E402
    CLIError,
    TOP_LEVEL_COMMANDS,
    canonicalize,
    resolve_command,
)


class CLITests(unittest.TestCase):
    def test_open_routes_outside_to_reader_and_inside_to_existing_bridge(self):
        from cosmos_tui.core.cli import main
        for integrated in (False, True):
            with self.subTest(integrated=integrated), patch('cosmos_tui.terminal.tmux.in_cosmos_pane', return_value=integrated), patch('cosmos_tui.features.reader.standalone.run') as reader, patch('cosmos_tui.core.cli.subprocess.call', return_value=0) as bridge:
                if integrated:
                    with self.assertRaises(SystemExit) as result:
                        main(['open', '/tmp/fixture.md'])
                    self.assertEqual(result.exception.code, 0)
                    reader.assert_not_called()
                    self.assertEqual(bridge.call_args.args[0][1:], ['open','/tmp/fixture.md'])
                else:
                    self.assertEqual(main(['open', '/tmp/fixture.md']), 0)
                    reader.assert_called_once_with('/tmp/fixture.md', mouse_mode='auto')
                    bridge.assert_not_called()

    def test_arche_development_version(self):
        result = subprocess.run(
            [str(ROOT / "cosmos"), "--version"], text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Cosmos Arche 0.2.3 (development)")

    def test_symlink_help_and_all_subcommand_help(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "cosmos"
            entry.symlink_to(ROOT / "cosmos")
            for arguments in (
                ["--help"],
                ["--version"],
                ["attach", "--help"],
                ["a", "--help"],
                ["attach-session", "--help"],
                ["n", "--help"],
                ["new-session", "--help"],
                ["list-sessions", "--help"],
                ["sessions", "--help"],
                ["kill-session", "--help"],
                ["has-session", "--help"],
                ["rename-session", "--help"],
                ["session", "--help"],
                ["session", "a", "--help"],
                ["session", "exists", "--help"],
                ["mod", "add", "--help"],
                ["rpc", "--help"],
                ["help", "completion"],
                ["help", "a"],
                ["help", "session", "rename"],
            ):
                result = subprocess.run(
                    [str(entry), *arguments], text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout)

    def test_help_uses_short_forms(self):
        result = subprocess.run(
            [str(ROOT / "cosmos"), "--help"], text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for form in (
            "[a]ttach",
            "[n]ew",
            "[l]ist",
            "[k]ill",
            "[ex]ists",
            "[re]name",
            "[hi]story",
        ):
            self.assertIn(form, result.stdout)

    def test_prefix_resolution_and_alias_precedence(self):
        self.assertEqual(resolve_command("a", TOP_LEVEL_COMMANDS).name, "attach")
        self.assertEqual(resolve_command("ac", TOP_LEVEL_COMMANDS).name, "action")
        self.assertEqual(resolve_command("att", TOP_LEVEL_COMMANDS).name, "attach")
        self.assertEqual(resolve_command("exi", TOP_LEVEL_COMMANDS).name, "exists")
        self.assertEqual(resolve_command("re", TOP_LEVEL_COMMANDS).name, "rename")
        self.assertEqual(resolve_command("hi", TOP_LEVEL_COMMANDS).name, "history")
        self.assertIsNone(resolve_command("research", TOP_LEVEL_COMMANDS))
        for ambiguous in ("h", "e", "s", "c", "d", "r"):
            with self.assertRaises(CLIError, msg=ambiguous):
                resolve_command(ambiguous, TOP_LEVEL_COMMANDS)
        self.assertEqual(
            canonicalize(["a", "-s", "research"]),
            (["[a]ttach", "-s", "research"], "attach"),
        )
        self.assertEqual(
            canonicalize(["session", "ex", "research"]),
            (["session", "[ex]ists", "research"], "exists"),
        )
        self.assertEqual(
            canonicalize(["research"]),
            (["[a]ttach", "research"], "attach"),
        )

    def test_ambiguous_command_is_reported(self):
        result = subprocess.run(
            [str(ROOT / "cosmos"), "h"], text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ambiguous command: h", result.stderr)
        self.assertIn("cosmos attach h", result.stderr)

    def test_completion_and_management_dispatch(self):
        script = subprocess.check_output(
            [str(ROOT / "cosmos"), "completion", "bash"], text=True
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                script
                + '\nCOMP_WORDS=(cosmos mod st); COMP_CWORD=2; _cosmos_complete; printf "%s\\n" "${COMPREPLY[@]}"',
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.stdout.splitlines(), ["start", "stop"])
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "coordinator"
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            binary.chmod(0o755)
            env = dict(os.environ, COSMOS_BINARY=str(binary))
            for arguments, expected in (
                (["rpc", "health", "{}"], ["rpc", "health", "{}"]),
                (["da"], ["daemon"]),
                (["con"], ["config"]),
                (["ac", "demo"], ["action", "demo"]),
            ):
                result = subprocess.run(
                    [str(ROOT / "cosmos"), *arguments],
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.stdout.splitlines(), expected, arguments)


if __name__ == "__main__":
    unittest.main()
