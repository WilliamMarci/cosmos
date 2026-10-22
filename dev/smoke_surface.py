#!/usr/bin/env python3
"""Cosmos-owned composition and Mod input, with tmux deliberately unavailable."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import tempfile
import termios
import time
import struct
ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / 'target/release/cosmos'

def until(condition):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.03)
    raise AssertionError('condition timed out')

def wait_text(fd, text):
    data = b''
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if select.select([fd], [], [], .05)[0]:
            data += os.read(fd, 65536)
            if text in data:
                return
    raise AssertionError(f'Missing rendered text {text!r}; tail: {data[-300:]!r}')

with tempfile.TemporaryDirectory(prefix='cosmos-surface-') as temp:
    env = dict(os.environ, XDG_RUNTIME_DIR=temp, XDG_CONFIG_HOME=f'{temp}/config',
               XDG_STATE_HOME=f'{temp}/state', COSMOS_TMUX=f'{temp}/no-tmux', TERM='xterm-256color')
    daemon = subprocess.Popen([str(BINARY), 'daemon'], env=env)
    def rpc(method, params=None):
        output = subprocess.run([str(BINARY), 'rpc', method, json.dumps(params or {})], env=env,
                                check=True, capture_output=True, text=True)
        return json.loads(output.stdout)
    panel = None
    fd = slave = None
    try:
        until(lambda: Path(temp, 'cosmos/control.sock').exists())
        subprocess.run([str(BINARY), 'mod', 'add', str(ROOT / 'examples/surface.mod.toml')], env=env,
                       check=True, capture_output=True)
        fd, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        panel = subprocess.Popen([str(BINARY), 'panel'], stdin=slave, stdout=slave, stderr=slave, env=env)
        wait_text(fd, b'Cosmos / actions')
        os.write(fd, b'Mods\r')
        wait_text(fd, b'Cosmos / mods')
        os.write(fd, b'interactive\r')
        wait_text(fd, b'Received keys: 0')
        # Unicode bytes split beyond the Escape timeout must stay one character.
        encoded = '中'.encode()
        os.write(fd, encoded[:2])
        time.sleep(.15)
        os.write(fd, encoded[2:])
        wait_text(fd, b'Received keys: 1')
        os.write(fd, b'\r')
        wait_text(fd, b'Received keys: 2')
        os.write(fd, b'?')
        wait_text(fd, b'Received keys: 3')
        os.write(fd, b'\x1b')
        wait_text(fd, b'Cosmos / mods')
        until(lambda: rpc('mods.list')[0]['status']['state'] == 'exited')
        # Source query was preserved; clear it, return to root, then exit.
        for _ in range(3):
            os.write(fd, b'\x1b')
            time.sleep(.15)
        assert panel.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        assert not rpc('state.snapshot')['ui']
        rpc('daemon.shutdown')
        assert daemon.wait(timeout=5) == 0
        print(json.dumps({'tmux_unavailable': True, 'mod_rendered_by_cosmos': 'passed',
                          'client_launch_context': 'passed', 'fragmented_unicode_input': 'passed',
                          'modal_key_isolation': 'passed', 'underlying_menu_restored': 'passed',
                          'terminal_and_lease_cleanup': 'passed'}))
    finally:
        if panel and panel.poll() is None:
            panel.terminate()
            panel.wait(timeout=5)
        if daemon.poll() is None:
            daemon.terminate()
            daemon.wait(timeout=5)
        if fd is not None:
            os.close(fd)
        if slave is not None:
            os.close(slave)
