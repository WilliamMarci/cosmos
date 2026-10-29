"""OpenCode configuration assembled from Cosmos-owned modules."""

import sys
from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.features.agent.profile import provider_config


def configuration(socket, source_pane):
    from cosmos_tui.features.agent.skills import commands, personal_skills, skill_paths

    return {
        **provider_config(),
        "skills": skill_paths(),
        "commands": commands(),
        "default_agent": "cosmos",
        "agents": {
            "cosmos": {
                "mode": "primary",
                "description": "Cosmos terminal workspace agent",
                "system": (PROJECT_ROOT / "config/cosmos-agent-prompt.md").read_text()
                + f"\nSource pane: {source_pane}. Cosmos Tmux service: {socket}.\n"
                + f"Personal Cosmos skill library: {personal_skills()}.\n"
                + f"Skill export helper Python: {sys.executable}.\n",
            }
        },
        "mcp": {
            "servers": {
                "cosmos_terminal": {
                    "type": "local",
                    "codemode": False,
                    "command": [
                        sys.executable,
                        "-m",
                        "cosmos_tui.features.agent",
                        "mcp",
                        "--socket",
                        socket,
                    ],
                    "environment": {"PYTHONPATH": str(PROJECT_ROOT / "python")},
                },
                "cosmos_actions": {
                    "type": "local",
                    "codemode": False,
                    "command": [
                        sys.executable,
                        "-m",
                        "cosmos_tui.features.agent",
                        "mcp",
                        "--socket",
                        socket,
                        "--toolset",
                        "actions",
                    ],
                    "environment": {"PYTHONPATH": str(PROJECT_ROOT / "python")},
                },
            }
        },
        "permissions": [
            {"action": "cosmos_actions_*", "resource": "*", "effect": "ask"},
            {
                "action": "cosmos_actions_list_actions",
                "resource": "*",
                "effect": "allow",
            },
            {"action": "cosmos_terminal_*", "resource": "*", "effect": "ask"},
            {"action": "cosmos_terminal_observe", "resource": "*", "effect": "allow"},
            {
                "action": "cosmos_terminal_list_sessions",
                "resource": "*",
                "effect": "allow",
            },
            {
                "action": "cosmos_terminal_list_panes",
                "resource": "*",
                "effect": "allow",
            },
            {
                "action": "cosmos_terminal_read_screen",
                "resource": "*",
                "effect": "allow",
            },
        ],
    }
