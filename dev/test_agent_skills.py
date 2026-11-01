"""Skill paths, prompt registration and portable export without a model call."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cosmos_tui.features.agent.launch import configuration, environment
from cosmos_tui.features.agent.skills import pack_skill, skill_paths, validate_skill
from cosmos_tui.core.paths import PROJECT_ROOT


class SkillTests(unittest.TestCase):
    def test_agent_environment_does_not_merge_foreign_config(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.dict(
                os.environ,
                HOME=root,
                XDG_CONFIG_HOME=str(Path(root) / "config"),
                XDG_DATA_HOME=str(Path(root) / "data"),
                OPENCODE_CONFIG="/foreign/opencode.json",
                OPENCODE_CONFIG_CONTENT='{"skills":["/foreign/skills"]}',
                OPENCODE_CLI_CONFIG_CONTENT='{"plugins":["foreign-plugin"]}',
            ),
        ):
            import json

            env = environment("service", "%12")
            self.assertEqual(env["HOME"], root)
            self.assertEqual(
                env["OPENCODE_CONFIG"],
                str(Path(root) / "config/cosmos/agent/opencode.json"),
            )
            self.assertEqual(
                env["XDG_DATA_HOME"], str(Path(root) / "config/cosmos/agent/data")
            )
            self.assertNotIn("OPENCODE_CLI_CONFIG_CONTENT", env)
            config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
            self.assertNotIn("/foreign/skills", config["skills"])
            self.assertEqual(
                set(config["mcp"]["servers"]), {"cosmos_terminal", "cosmos_actions"}
            )

    def test_library_paths_and_export_prompt(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.dict(os.environ, XDG_CONFIG_HOME=root),
        ):
            paths = skill_paths(root)
            self.assertEqual(paths[1], str(Path(root) / "cosmos/agent/skills"))
            self.assertEqual(paths[2], str(Path(root) / ".cosmos/skills"))
            config = configuration("service", "%12")
            self.assertIn("agent-learn", config["commands"])
            learned = config["commands"]["agent-learn"]["template"]
            self.assertIn("$ARGUMENTS", learned)
            self.assertIn("isolated Cosmos profile", learned)
            self.assertIn("cosmos_task", learned)
            self.assertIn("cosmos-export-skill", config["commands"])
            self.assertIn(
                "$ARGUMENTS", config["commands"]["cosmos-export-skill"]["template"]
            )
            self.assertIn(paths[1], config["agents"]["cosmos"]["system"])
            self.assertFalse((Path(root) / "cosmos/agent/skills").exists())

    def test_builtin_skill_export_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            output = pack_skill(
                PROJECT_ROOT / "skills/cosmos-skill-export", Path(root) / "skill.zip"
            )
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {
                        "cosmos-skill-export/SKILL.md",
                        "cosmos-skill-export/references/skill-template.md",
                    },
                )
                archive.extractall(Path(root) / "imported")
            _, metadata, files = validate_skill(
                Path(root) / "imported/cosmos-skill-export"
            )
            self.assertEqual(metadata["name"], "cosmos-skill-export")
            self.assertEqual(len(files), 2)
            with self.assertRaises(FileExistsError):
                pack_skill(PROJECT_ROOT / "skills/cosmos-skill-export", output)

    def test_export_rejects_nonportable_reference(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "demo"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Example workflow\n---\nSee [steps](references/missing.md).\n"
            )
            with self.assertRaisesRegex(ValueError, "reference"):
                pack_skill(source, Path(root) / "demo.zip")
            self.assertFalse((Path(root) / "demo.zip").exists())
