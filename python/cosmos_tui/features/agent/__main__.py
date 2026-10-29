"""Private Agent entrypoint used by Cosmos and OpenCode MCP configuration."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Cosmos Agent development runtime")
    parser.add_argument("mode", choices=("launch", "mcp"))
    parser.add_argument("--socket", required=True)
    parser.add_argument("--source-pane", default="")
    parser.add_argument("--prompt", default="")
    parser.add_argument(
        "--toolset", choices=("terminal", "actions"), default="terminal"
    )
    args = parser.parse_args()
    if args.mode == "mcp":
        from cosmos_tui.features.agent.mcp import serve

        serve(args.socket, args.toolset)
    else:
        from cosmos_tui.features.agent.launch import launch

        launch(args.socket, args.source_pane, args.prompt)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"cosmos agent: {error}", file=sys.stderr)
        raise SystemExit(1)
