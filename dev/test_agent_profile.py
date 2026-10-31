"""Private profile, secret isolation, configuration and theme regressions."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cosmos_tui.features.agent import profile
from cosmos_tui.features.agent.launch import environment
from cosmos_tui.features.agent.theme import install_theme


class ProfileTests(unittest.TestCase):
    def test_permissions_credentials_and_environment(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CONFIG_HOME=directory),
        ):
            root = profile.initialize_profile()
            secret = root / "credentials.json"
            secret.write_text(json.dumps({"deepseek": "fixture-secret"}))
            secret.chmod(0o644)
            script = root / "helper"
            script.write_text("#!/bin/sh\n")
            script.chmod(0o755)
            profile.secure_profile()
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
            self.assertEqual(script.stat().st_mode & 0o777, 0o700)
            env = environment("fixture", "%0")
            self.assertEqual(env["COSMOS_AGENT_API_KEY"], "fixture-secret")
            self.assertNotIn("fixture-secret", env["OPENCODE_CONFIG_CONTENT"])
            with patch.dict(os.environ, env):
                self.assertEqual(profile.profile_root(), root)
            install_theme()
            self.assertEqual(
                json.loads((root / "cli.json").read_text())["theme"]["name"], "cosmos"
            )
            (root / "cli.json").write_text('{"theme":{"name":"custom"}}')
            install_theme()
            self.assertIn("custom", (root / "cli.json").read_text())
            outside = Path(directory) / "outside"
            outside.mkdir(mode=0o755)
            profile.write_private_json(outside / "export.json", {})
            self.assertEqual(outside.stat().st_mode & 0o777, 0o755)
            (root / "escape").symlink_to(outside)
            with self.assertRaises(ValueError):
                profile.secure_profile()

    def test_configuration_and_validation(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CONFIG_HOME=directory),
        ):
            profile.initialize_profile()
            config = profile.provider_config()
            self.assertEqual(config["model"]["providerID"], "deepseek")
            self.assertEqual(
                config["providers"]["deepseek"]["package"], "@opencode/ai/providers/deepseek"
            )
            for values in (
                {"provider": "opencode"},
                {"base_url": "https://user:key@example.com"},
            ):
                with self.assertRaises(ValueError):
                    profile.configure(**values)
            self.assertEqual(profile.load_profile()[0], profile.DEFAULTS)

    def test_migration_does_not_overwrite(self):
        from cosmos_tui.features.agent.migration import migrate

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                XDG_CONFIG_HOME=directory,
                XDG_DATA_HOME=directory + "/data",
                XDG_STATE_HOME=directory + "/state",
                XDG_CACHE_HOME=directory + "/cache",
            ),
        ):
            old = Path(directory) / "cosmos/skills/example"
            old.mkdir(parents=True)
            (old / "SKILL.md").write_text("fixture")
            moved = migrate()
            self.assertEqual(len(moved), 1)
            self.assertTrue(
                (profile.profile_root() / "skills/example/SKILL.md").exists()
            )
            old.mkdir(parents=True)
            with self.assertRaises(ValueError):
                migrate()
            self.assertTrue(old.exists())
