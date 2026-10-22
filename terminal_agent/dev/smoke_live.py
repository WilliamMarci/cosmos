"""Opt-in real-model integration smoke. Generates a command; NEVER executes it."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ta-live-') as tmp:
        folder = Path(tmp)
        snapshot = folder / 'buffer'
        rc = folder / 'bashrc'
        rc.write_text(f'''PS1='LIVE> '
HISTFILE=/dev/null
source {ROOT}/shell/agent.bash
_snapshot() {{ printf '%s' "$READLINE_LINE" > {snapshot}; }}
bind -x '"\\C-x\\C-b":_snapshot'
''')
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 120, 0, 0))
        env = dict(os.environ, TERM='xterm-256color', TERMINAL_AGENT_PYTHON=sys.executable,
                   PROMPT_TOOLKIT_NO_CPR='1')
        env.pop('TERMINAL_AGENT_DEMO', None)
        process = subprocess.Popen(['bash', '--noprofile', '--rcfile', str(rc), '-i'],
            stdin=slave, stdout=slave, stderr=slave, cwd=folder, env=env,
            start_new_session=True)
        os.close(slave)
        transcript = bytearray()

        def pump(seconds):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                if select.select([master], [], [], .05)[0]:
                    try:
                        transcript.extend(os.read(master, 65536))
                    except OSError:
                        break

        try:
            pump(.5)
            marker = len(transcript)
            os.write(master, b'\x18\x01')
            pump(.5)
            os.write(master, '将当前目录的PNG图片按文件名顺序合并为一个PDF。只生成命令，不执行。\r'.encode())
            print('Waiting for real model proposal...', flush=True)
            until = time.monotonic() + args.timeout
            while b'.pdf' not in transcript[marker:].lower() and time.monotonic() < until:
                pump(.25)
            if b'.pdf' not in transcript[marker:].lower():
                raise RuntimeError('No PDF command appeared before timeout; terminal tail: ' + repr(bytes(transcript[-1000:])))
            pump(.5)
            repaint = bytes(transcript[marker:])
            os.write(master, b'\t')  # Native editor; no Enter is sent here.
            pump(.4)
            os.write(master, b'\x18\x02')
            pump(.4)
            command = snapshot.read_text()
            assert '.pdf' in command.lower(), command
            os.write(master, b'\t')
            pump(.4)
            os.write(master, b'\x1b')  # End the assistant session, retaining buffer.
            pump(.4)
            os.write(master, b'\x18\x02')
            pump(.4)
            assert snapshot.read_text() == command
            assert not list(folder.glob('*.pdf'))
            assert {p.name for p in folder.iterdir()} <= {'bashrc', 'buffer'}, 'unexpected files in target directory'
            assert b'LIVE>' not in repaint, 'normal generation repainted PS1'
            spinner = sorted(set('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏') & set(repaint.decode(errors='replace')))
            assert len(spinner) > 1, 'no running animation observed'
            from terminal_agent.backend import OpenCode
            from terminal_agent.config import load
            backend = OpenCode(load())
            report = {'model': backend.model(), 'command': command, 'executed': False,
                      'native_buffer_preserved': True, 'prompt_repainted': False,
                      'spinner_frames_observed': spinner, 'state_directory': str(backend.storage.root),
                      'original_opencode_database': 'read-only credentials and public model metadata',
                      'opencode_session_database': str(backend.storage.data / 'opencode/opencode.db')}
            (ROOT / 'dev/live-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            os.close(master)


if __name__ == '__main__':
    main()
