"""Public entry works through symlinks, without starting services for help."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def test_symlink_help_and_all_subcommand_help(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "cosmos"
            entry.symlink_to(ROOT / "cosmos")
            for arguments in (
                ["--help"],
                ["--version"],
                ["attach", "--help"],
                ["mod", "add", "--help"],
                ["rpc", "--help"],
                ["help", "completion"],
            ):
                result = subprocess.run(
                    [str(entry), *arguments], text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout)

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
            result = subprocess.run(
                [str(ROOT / "cosmos"), "rpc", "health", "{}"],
                env=dict(os.environ, COSMOS_BINARY=str(binary)),
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.stdout.splitlines(), ["rpc", "health", "{}"])


if __name__ == "__main__":
    unittest.main()
