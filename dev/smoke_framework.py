#!/usr/bin/env python3
"""Real terminal panel + external Python Mod acceptance, isolated state."""
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

def wait_output(fd, marker):
    data = b''
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if select.select([fd], [], [], 0.05)[0]:
            data += os.read(fd, 65536)
            if marker in data:
                return
    raise AssertionError(f'panel output missing: {marker!r}')

def until(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError('condition timed out')

with tempfile.TemporaryDirectory(prefix='cosmos-framework-smoke-') as temp:
    env = dict(os.environ, XDG_RUNTIME_DIR=temp, XDG_CONFIG_HOME=f'{temp}/config',
               XDG_STATE_HOME=f'{temp}/state', TERM='xterm-256color',
               COSMOS_TMUX=f'{temp}/deliberately-unavailable-tmux',
               COSMOS_TMUX_SOCKET=f'cosmos-framework-smoke-{os.getpid()}')
    daemon = subprocess.Popen([str(BINARY), 'daemon'], env=env)
    def rpc(method, params=None):
        result = subprocess.run([str(BINARY), 'rpc', method, json.dumps(params or {})],
                                env=env, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    panel = None
    fd = None
    slave = None
    try:
        until(lambda: Path(temp, 'cosmos/control.sock').exists())
        subprocess.run([str(BINARY), 'mod', 'add', str(ROOT / 'examples/demo.mod.toml')],
                       env=env, check=True, capture_output=True)
        rpc('mods.start', {'id': 'demo'})
        until(lambda: rpc('mods.list')[0]['status']['state'] == 'ready')
        until(lambda: any(n['text'] == 'Demo Mod ready' for n in rpc('notifications.list', {'client': 'smoke'})))
        fd, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 20, 70, 0, 0))
        panel = subprocess.Popen([str(BINARY), 'panel'], env=env, stdin=slave, stdout=slave, stderr=slave)
        wait_output(fd, b'Cosmos / actions')
        os.write(fd, b'\r')
        wait_output(fd, b'Cosmos / settings')
        os.write(fd, b'Display\r')
        wait_output(fd, b'Cosmos / display')
        os.write(fd, b'Toggle dark\r')
        until(lambda: rpc('settings.get')['theme'] == 'light')
        until(lambda: any(e['topic'] == 'mod.demo.theme'
                          for e in rpc('events.poll', {'after': 0})['events']))
        os.write(fd, b'?')
        wait_output(fd, b'choose action')
        # Exercise narrow resize while help is active.
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 5, 18, 0, 0))
        until(lambda: any(c['width'] == 18 for c in rpc('state.snapshot')['ui']))
        os.write(fd, b'?')
        until(lambda: all(len(c['views']) == 1 for c in rpc('state.snapshot')['ui']))
        time.sleep(0.1)
        # Normal termination must also run the terminal and UI lease guards.
        panel.send_signal(signal.SIGTERM)
        assert panel.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original, 'terminal attributes were not restored'
        until(lambda: not rpc('state.snapshot')['ui'])
        rpc('mods.stop', {'id': 'demo'})
        until(lambda: rpc('mods.list')[0]['status']['state'] == 'stopped')
        rpc('daemon.shutdown')
        assert daemon.wait(timeout=5) == 0
        print(json.dumps({'external_mod_ready': 'passed', 'mod_event_delivery': 'passed',
                          'panel_submenus': 'passed', 'pasted_filter_and_enter': 'passed',
                          'theme_setting': 'passed', 'resize': 'passed',
                          'terminal_restoration': 'passed', 'lease_cleanup': 'passed',
                          'graceful_shutdown': 'passed'}))
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
