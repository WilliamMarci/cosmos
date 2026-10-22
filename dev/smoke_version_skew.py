#!/usr/bin/env python3
"""Regression: an old live coordinator must produce a visible popup error."""
import json
import os
from pathlib import Path
import pty
import select
import socket
import subprocess
import tempfile
import termios
import threading
import time

BINARY = Path(__file__).resolve().parents[1] / 'target/release/cosmos'
with tempfile.TemporaryDirectory(prefix='cosmos-old-service-') as temp:
    directory = Path(temp, 'cosmos')
    directory.mkdir(mode=0o700)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(directory / 'control.sock'))
    listener.listen()
    listener.settimeout(0.1)
    stopping = threading.Event()
    operations = []
    def serve():
        while not stopping.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection, connection.makefile('rwb') as stream:
                connection.settimeout(2)
                for line in stream:
                    request = json.loads(line)
                    operations.append(request['method'])
                    if request['method'] == 'initialize':
                        value = {'protocol_major': 1, 'protocol_minor': 0,
                                 'capabilities': ['settings'], 'service_epoch': 'old'}
                    else:
                        value = {'status': 'ready'}
                    stream.write(json.dumps({'jsonrpc': '2.0', 'id': request['id'],
                                             'result': value}).encode() + b'\n')
                    stream.flush()
    task = threading.Thread(target=serve)
    task.start()
    fd, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, XDG_RUNTIME_DIR=temp, XDG_CONFIG_HOME=f'{temp}/config')
    process = subprocess.Popen([str(BINARY), 'panel', '--popup'], env=env,
                               stdin=slave, stdout=slave, stderr=slave)
    try:
        data = b''
        deadline = time.monotonic() + 5
        while b'Press Enter to close' not in data and time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                data += os.read(fd, 65536)
        assert b'protocol 1.0' in data, data
        assert b'Press Enter to close' in data, data
        assert process.poll() is None, 'error popup disappeared before acknowledgment'
        assert 'ui.attach' not in operations, 'terminal state acquired before compatibility check'
        os.write(fd, b'\n')
        assert process.wait(timeout=3) == 1
        assert termios.tcgetattr(slave) == original
        assert 'protocol 1.0' in (directory / 'panel-error.log').read_text()
        print(json.dumps({'old_service_rejected_before_ui': 'passed',
                          'error_retained_until_acknowledgment': 'passed',
                          'terminal_unchanged': 'passed', 'diagnostic_log': 'passed'}))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        stopping.set()
        task.join(timeout=3)
        listener.close()
        os.close(fd)
        os.close(slave)
