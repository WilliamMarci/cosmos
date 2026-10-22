import argparse
import os
import json
from pathlib import Path
import subprocess
import sys
from .config import load
from .backend import OpenCode, Demo
from .storage import Storage
from .ui import InlineUI
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI


def main():
    parser = argparse.ArgumentParser(description='Inline shell assistant: Enter generate, Tab native Bash editor, Enter there to run, Esc close')
    parser.add_argument('request', nargs='*')
    parser.add_argument('--demo', action='store_true', help='Use a fixed proposal; direct launch previews its own editor, not Bash')
    parser.add_argument('--config')
    parser.add_argument('--output', help='Write editor contents to this file (shell integration)')
    parser.add_argument('--state', help=argparse.SUPPRESS)
    parser.add_argument('--readline', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--shell', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--cosmos-ui', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--source-geometry', default='{}', help=argparse.SUPPRESS)
    parser.add_argument('--shell-line', default='', help=argparse.SUPPRESS)
    parser.add_argument('--shell-point', type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--shell-prompt', default='$ ', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('requires an interactive terminal')
    try:
        if not args.shell:
            print('独立预览：不会修改父 Bash 编辑区。原生模式请 source shell/agent.bash 后按 Ctrl-X Ctrl-A。', file=sys.stderr)
        config = load(args.config)
        backend = Demo() if args.demo else OpenCode(config)
        cursor = min(len(args.shell_line), max(0, args.shell_point))
        ui = InlineUI(backend, initial=' '.join(args.request),
                      command=args.shell_line if args.shell else '',
                      command_cursor=cursor if args.shell else None,
                      prompt=args.shell_prompt if args.shell else '$ ', shell_mode=args.shell,
                      native_overlay=args.readline)
        if args.state and Path(args.state).exists():
            state = json.loads(Path(args.state).read_text())
            ui.cosmos_ui = state.get('cosmos_ui', {})
            ui.history = state.get('history', [])
            ui.request_history = state.get('request_history', [item['request'] for item in ui.history if isinstance(item.get('request'), str)])
            index, draft = state.get('history_index'), state.get('history_draft')
            if (isinstance(index, int) and 0 <= index < len(ui.request_history)
                    and isinstance(draft, list) and len(draft) == 2
                    and isinstance(draft[0], str) and isinstance(draft[1], int)):
                ui.history_index, ui.history_draft = index, tuple(draft)
            ui.input.text = state.get('request', '')
            ui.input.buffer.cursor_position = state.get('cursor', len(ui.input.text))
        from . import cosmos_bridge
        address = cosmos_bridge.endpoint() if args.shell else None
        if args.shell and (args.cosmos_ui or os.environ.get("TERMINAL_AGENT_COSMOS_UI") == "1") and not address:
            raise OSError("Cosmos UI disconnected; command was not executed")
        if address:
            action, command = cosmos_bridge.run(ui, address, demo=args.demo, geometry=json.loads(args.source_geometry))
        else:
            action, command = ui.run()
        if args.state:
            context = {'history': ui.history, 'request_history': ui.request_history,
                       'history_index': ui.history_index, 'history_draft': ui.history_draft,
                       'request': ui.input.text,
                       'cursor': ui.input.buffer.cursor_position, 'cosmos_ui': getattr(ui, 'cosmos_ui', {}),
                       'working_directory': os.getcwd(), 'command': ui.command.text}
            Path(args.state).write_text(json.dumps(context))
            if config.get('persist_sessions', True) and not args.demo:
                Storage(config).save_session(Path(args.state).parent.name, context)
        if args.output:
            # Esc closes only the popup: keep the latest editor contents, including
            # generated or manually edited commands and the cursor position.
            if action == 'edit' and args.readline and not address:
                body, buttons = ui.passive_snapshot()
                Path(args.output + '.bar').write_text(body)
                Path(args.output + '.buttons').write_text(buttons)
            if address:
                Path(args.output + '.bar').write_text('')
                Path(args.output + '.buttons').write_text('')
            Path(args.output).write_text(ui.command.text)
            Path(args.output + '.point').write_text(str(ui.command.buffer.cursor_position))
            Path(args.output + '.action').write_text(action if action != 'agent' else 'cancel')
            if action == 'agent':
                return subprocess.call(backend.interactive(command))
            return 0
        print_formatted_text(ANSI(ui.prompt), end='')
        print(ui.command.text)
        if action == 'run':
            return subprocess.call(command, shell=True, executable=os.environ.get('SHELL', '/bin/bash'))
        if action == 'agent':
            return subprocess.call(backend.interactive(command))
        return 0
    except (OSError, ValueError) as exc:
        print(f'agent: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
