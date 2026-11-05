#!/usr/bin/env python3
"""Real PTY attach/detach/re-attach smoke, using an isolated tmux server."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / 'target/release/cosmos'

def wait_text(fd, needle):
    data = b''
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if select.select([fd], [], [], 0.1)[0]:
            data += os.read(fd, 65536)
            if needle in data:
                return
    raise AssertionError(f'expected PTY marker {needle!r}')

def attach(env, command, expected):
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(BINARY, [str(BINARY), 'native'], env)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
        wait_text(fd, b'cosmos')
        os.write(fd, command + b'\n')
        wait_text(fd, expected)
        os.write(fd, b'\x02p')
        wait_text(fd, b'Cosmos / actions')
        os.write(fd, b'\x1b')
        wait_text(fd, expected)
        os.write(fd, b'\x02d')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                assert os.waitstatus_to_exitcode(status) == 0
                return
            time.sleep(0.05)
        raise AssertionError('attach failed to detach')
    finally:
        os.close(fd)
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except ProcessLookupError:
            pass
        except ChildProcessError:
            pass

with tempfile.TemporaryDirectory(prefix='cosmos-smoke-') as temp:
    env = dict(os.environ, XDG_RUNTIME_DIR=temp, XDG_CONFIG_HOME=f'{temp}/config', XDG_STATE_HOME=f'{temp}/state',
               COSMOS_TMUX_SOCKET=f'cosmos-smoke-{os.getpid()}', TERM='xterm-256color')
    daemon = subprocess.Popen([str(BINARY), 'daemon'], env=env)
    try:
        for _ in range(100):
            if Path(temp, 'cosmos/control.sock').exists():
                break
            time.sleep(0.01)
        attach(env, b"export COSMOS_SMOKE=retained; printf 'first:%s\\n' ok", b'first:ok')
        attach(env, b"printf 'state:%s\\n' \"$COSMOS_SMOKE\"", b'state:retained')
        result = subprocess.run([str(BINARY), 'rpc', 'objects.list'], env=env,
                                check=True, capture_output=True, text=True)
        assert len(json.loads(result.stdout)['panes']) == 1
        print(json.dumps({'attach': 'passed', 'detach': 'passed',
                          'reattach_shell_state': 'retained', 'pane_inventory': 'passed'}))
    finally:
        subprocess.run([os.getenv('COSMOS_TMUX', 'tmux'), '-L', env['COSMOS_TMUX_SOCKET'], 'kill-server'],
                       capture_output=True, env=env)
        daemon.terminate()
        daemon.wait(timeout=5)
