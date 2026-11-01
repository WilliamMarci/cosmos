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
                + f"\nSource terminal: {source_pane}. Workspace connection is managed by Cosmos.\n"
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
            {"action": "shell", "resource": "*", "effect": "ask"},
            {
                "action": "cosmos_terminal_workspace_info",
                "resource": "*",
                "effect": "allow",
            },
            {"action": "cosmos_actions_*", "resource": "*", "effect": "ask"},
            *[
                dict(action=name, resource="*", effect="allow")
                for name in (
                    "cosmos_actions_list_clients",
                    "cosmos_actions_client_context",
                    "cosmos_actions_reader_events",
                )
            ],
            {
                "action": "cosmos_actions_list_actions",
                "resource": "*",
                "effect": "allow",
            },
            {"action": "cosmos_terminal_*", "resource": "*", "effect": "ask"},
            *[
                dict(action="cosmos_terminal_" + name, resource="*", effect="allow")
                for name in ("list_tasks", "task_history", "finish_task")
            ],
            {
                "action": "cosmos_terminal_read_history",
                "resource": "*",
                "effect": "allow",
            },
            {
                "action": "cosmos_terminal_resolve_target",
                "resource": "*",
                "effect": "allow",
            },
            {
                "action": "cosmos_terminal_control_status",
                "resource": "*",
                "effect": "allow",
            },
            {
                "action": "cosmos_terminal_terminal_watches",
                "resource": "*",
                "effect": "allow",
            },
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
