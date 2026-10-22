"""Optional Cosmos presentation transport. The standalone UI remains unchanged."""
import json
import os
import socket
import subprocess


def endpoint():
    if not os.environ.get('TMUX_PANE') or not os.environ.get('TMUX'):
        return None
    result = subprocess.run(['tmux', '-S', os.environ['TMUX'].split(',')[0],
        'show-options', '-pqv', '-t', os.environ['TMUX_PANE'], '@cosmos_agent_socket'],
        capture_output=True, text=True, timeout=2)
    address = result.stdout.strip() if result.returncode == 0 else None
    return address if address and os.path.exists(address) else None


def snapshot(ui):
    return dict(history=ui.history, request_history=ui.request_history,
                history_index=ui.history_index, history_draft=ui.history_draft,
                request=ui.input.text, cursor=ui.input.buffer.cursor_position,
                command=ui.command.text, command_cursor=ui.command.buffer.cursor_position)


def restore(ui, state):
    for name in ('history', 'request_history', 'history_index', 'history_draft'):
        if name in state:
            setattr(ui, name, state[name])
    ui.input.text = state.get('request', '')
    ui.input.buffer.cursor_position = state.get('cursor', len(ui.input.text))
    ui.command.text = state.get('command', '')
    ui.command.buffer.cursor_position = state.get('command_cursor', len(ui.command.text))


def run(ui, address, demo=False):
    request = dict(version=1, pane=os.environ['TMUX_PANE'], cwd=os.getcwd(),
                   anchor_below=os.environ.get("TERMINAL_AGENT_COSMOS_UI") == "1",
                   prompt=ui.prompt, demo=demo, config=getattr(ui.backend, "config", {}), state=snapshot(ui))
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(address)
        client.settimeout(None)
        client.sendall(json.dumps(request).encode() + b'\n')
        with client.makefile('rb') as reader:
            data = reader.readline(1024 * 1024 + 1)
        if not data or len(data) > 1024 * 1024:
            raise OSError('Cosmos UI disconnected; command was not executed')
        response = json.loads(data)
    restore(ui, response['state'])
    return response['action'], ui.command.text
