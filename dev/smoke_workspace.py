#!/usr/bin/env python3
"""End-to-end Cosmos-owned workspace: shell, overlay, layout, app, detach/reconnect."""
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

def wait_text(fd, text, timeout=8):
    data = b''
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if select.select([fd], [], [], .05)[0]:
            data += os.read(fd, 65536)
            if text in data:
                return data
    raise AssertionError(f'workspace did not render {text!r}: {data[-600:]!r}')

def wait_exit(process):
    assert process.wait(timeout=5) == 0

def until(condition):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.03)
    raise AssertionError('condition timed out')

with tempfile.TemporaryDirectory(prefix='cosmos-workspace-') as temp:
    env = dict(os.environ, XDG_RUNTIME_DIR=temp, XDG_CONFIG_HOME=f'{temp}/config',
               XDG_STATE_HOME=f'{temp}/state', COSMOS_TMUX_SOCKET=f'cosmos-workspace-{os.getpid()}',
               TERM='xterm-256color', HISTFILE='/dev/null')
    daemon = subprocess.Popen([str(BINARY), 'daemon'], env=env)
    def rpc(method, params=None):
        result = subprocess.run([str(BINARY), 'rpc', method, json.dumps(params or {})], env=env,
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    def tmux(*args):
        return subprocess.run(['tmux', '-L', env['COSMOS_TMUX_SOCKET'], *args], check=True,
                              capture_output=True, text=True, env=env).stdout
    clients = []
    handles = []
    def launch(session=None):
        fd, slave = pty.openpty()
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 90, 0, 0))
        original = termios.tcgetattr(slave)
        process = subprocess.Popen([str(BINARY)] if session is None else [str(BINARY), "workspace", session], env=env,
                                   stdin=slave, stdout=slave, stderr=slave)
        clients.append(process)
        handles.extend([fd, slave])
        wait_text(fd, b'cosmos ')
        return process, fd, slave, original
    try:
        until(lambda: Path(temp, 'cosmos/control.sock').exists())
        subprocess.run([str(BINARY), 'mod', 'add', str(ROOT / 'examples/surface.mod.toml')], env=env, check=True, capture_output=True)
        process, fd, slave, original = launch()
        os.write(fd, b"export COSMOS_WS=kept; printf 'shell:%s\\n' ready\r")
        wait_text(fd, b'shell:ready')
        # Ctrl-C belongs to the application, not the Cosmos client process.
        os.write(fd, b'sleep 20\r')
        time.sleep(.2)
        os.write(fd, b'\x03')
        os.write(fd, b"printf 'interrupt:%s\\n' survived\r")
        wait_text(fd, b'interrupt:survived')
        assert process.poll() is None
        pane_before = tmux('display-message', '-p', '-t', 'main', '#{pane_id} #{pane_width} #{pane_height}').strip()
        os.write(fd, b'\x02p')
        wait_text(fd, b'Cosmos / actions')
        assert tmux('display-message', '-p', '-t', 'main', '#{pane_id} #{pane_width} #{pane_height}').strip() == pane_before
        # Output continues while the panel owns the display and input.
        tmux('send-keys', '-t', 'main', "printf 'background:%s\\n' continues", 'Enter')
        time.sleep(.2)
        os.write(fd, b'\x1b')
        wait_text(fd, b'background:continues')
        os.write(fd, b'\x02p')
        wait_text(fd, b'Cosmos / actions')
        os.write(fd, b'Mods\rinteractive\r')
        wait_text(fd, b'Received keys: 0')
        os.write(fd, b'k')
        wait_text(fd, b'Received keys: 1')
        assert tmux('display-message', '-p', '-t', 'main', '#{pane_id} #{pane_width} #{pane_height}').strip() == pane_before
        # Leader must work even while a Mod owns modal input.
        os.write(fd, b'\x02d')
        wait_exit(process)
        assert termios.tcgetattr(slave) == original
        until(lambda: rpc('mods.list')[0]['status']['state'] == 'exited')
        process, fd, slave, original = launch()
        os.write(fd, b'\x02%')
        until(lambda: len(tmux('list-panes', '-t', 'main', '-F', '#{pane_id}').splitlines()) == 2)
        os.write(fd, b"printf 'split:%s\\n' ready\r")
        wait_text(fd, b'split:ready')
        os.write(fd, b'\x02z')
        until(lambda: tmux('display-message', '-p', '-t', 'main', '#{window_zoomed_flag}').strip() == '1')
        os.write(fd, b'\x02z')
        # Create and switch windows using Cosmos-owned leader handling.
        os.write(fd, b'\x02c')
        until(lambda: len(tmux('list-windows', '-t', 'main').splitlines()) == 2)
        os.write(fd, b"printf 'window:%s\\n' second\r")
        wait_text(fd, b'window:second')
        # Real fullscreen alternate-screen application through the bridge.
        testfile = Path(temp, 'editor.txt')
        testfile.write_text('COSMOS_EDITOR_CONTENT\n')
        os.write(fd, f'vim -u NONE -i NONE -n -N {testfile}\r'.encode())
        wait_text(fd, b'COSMOS_EDITOR_CONTENT')
        os.write(fd, b'G')
        os.write(fd, b':q!\r')
        until(lambda: tmux('display-message', '-p', '-t', 'main', '#{pane_current_command}').strip() != 'vim')
        os.write(fd, b"printf 'editor:%s\\n' returned\r")
        wait_text(fd, b'editor:returned')
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 110, 0, 0))
        until(lambda: tmux('display-message', '-p', '-t', 'main', '#{pane_width}').strip() == '110')
        os.write(fd, b'\x02d')
        wait_exit(process)
        assert termios.tcgetattr(slave) == original
        # Shells and layout survive client disconnection.
        assert len(tmux('list-windows', '-t', 'main').splitlines()) == 2
        process, fd, slave, original = launch()
        os.write(fd, b'\x02b')
        os.write(fd, b'\x02o')
        os.write(fd, b"printf 'reconnect:%s\\n' \"$COSMOS_WS\"\r")
        wait_text(fd, b'reconnect:kept')
        os.write(fd, b'\x02d')
        wait_exit(process)
        assert termios.tcgetattr(slave) == original
        assert not rpc('state.snapshot')['ui']
        process, fd, slave, original = launch('exitcheck')
        os.write(fd, b'exit\r')
        wait_exit(process)
        assert termios.tcgetattr(slave) == original
        print(json.dumps({'own_workspace_rendering': 'passed', 'shell_and_ctrl_c': 'passed',
                          'panel_no_pty_resize': 'passed', 'workspace_mod_surface': 'passed', 'leader_inside_mod': 'passed', 'background_output': 'passed',
                          'split_zoom_windows': 'passed', 'vim_alternate_screen': 'passed',
                          'resize': 'passed', 'detach_and_reconnect': 'passed',
                          'terminal_restore': 'passed', 'last_shell_exit': 'passed'}))
    finally:
        for process in clients:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        subprocess.run(['tmux', '-L', env['COSMOS_TMUX_SOCKET'], 'kill-server'], env=env, capture_output=True)
        if daemon.poll() is None:
            daemon.terminate()
            daemon.wait(timeout=5)
        for fd in handles:
            os.close(fd)
