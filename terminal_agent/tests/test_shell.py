"""Exercise the adapter in a real Bash + Readline process, using a PTY."""
import os
import signal
import pathlib
import pty
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time
import unittest
import sys
import fcntl

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('bash'), 'requires Bash')
class ShellIntegrationTests(unittest.TestCase):
    def test_native_editor_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            snapshot = folder / 'snapshot'
            rc = folder / 'bashrc'
            rc.write_text(f'''PS1='TEST> '
HISTFILE=/dev/null
source {ROOT}/shell/agent.bash
_snapshot() {{
    printf '%s' "$READLINE_LINE" > {snapshot}
    printf '%s' "$READLINE_POINT" > {snapshot}.point
    bind -p > {folder}/bindings

}}
bind -x '"\\C-x\\C-b":_snapshot'
''')
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 100, 0, 0))
            env = dict(os.environ, TERM='xterm-256color',
                       TERMINAL_AGENT_PYTHON=sys.executable, TERMINAL_AGENT_DEMO='1',
                       PROMPT_TOOLKIT_NO_CPR='1', XDG_RUNTIME_DIR=tmp)
            env.pop('NO_COLOR', None)
            proc = subprocess.Popen(['bash', '--noprofile', '--rcfile', str(rc), '-i'],
                stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env,
                start_new_session=True)
            os.close(slave)
            transcript = bytearray()

            def pump(seconds=.3):
                until = time.monotonic() + seconds
                while time.monotonic() < until:
                    if select.select([master], [], [], .02)[0]:
                        try:
                            transcript.extend(os.read(master, 65536))
                        except OSError:
                            break

            def send(value, delay=.3):
                os.write(master, value.encode() if isinstance(value, str) else value)
                pump(delay)

            def inspect_line():
                send('\x18\x02')
                return snapshot.read_text()

            try:
                pump()
                # Escape restores the buffer and all unrelated Bash bindings.
                send('printf ORIGINAL')
                self.assertEqual(inspect_line(), 'printf ORIGINAL')
                bindings_before = (folder / 'bindings').read_text()
                send('\x18\x01')
                send('\x1b', .5)
                self.assertEqual(inspect_line(), 'printf ORIGINAL')
                self.assertEqual((folder / 'bindings').read_text(), bindings_before)

                # Generating exits through Bash to update READLINE_LINE, then
                # reopens only the popup. Tab releases all keys to Readline.
                repaint_start = len(transcript)
                send('\x18\x01')
                send('convert images\r', 1.0)
                self.assertNotIn(b'TEST>', transcript[repaint_start:], 'agent must not repaint PS1')
                unchanged = len(transcript)
                send('same command again\r', .8)
                self.assertNotIn(b'magick', transcript[unchanged:], 'unchanged command must not be repainted')
                send('\t', .5)
                self.assertEqual(inspect_line(), "magick '*.png' images.pdf")
                # This is a Bash-only bind -x callback: the Python UI cannot
                # handle it. Its success demonstrates native editing ownership.
                send('\x05 --native')
                self.assertEqual(inspect_line(), "magick '*.png' images.pdf --native")
                send('\t')
                send('\x1b', .5)
                self.assertEqual(inspect_line(), "magick '*.png' images.pdf --native")
                self.assertEqual((folder / 'bindings').read_text(), bindings_before)

                # Native Unicode editing/cursor survives a popup round trip.
                send('\x01\x0bprintf 中文\x02')
                self.assertEqual(inspect_line(), 'printf 中文')
                point = pathlib.Path(str(snapshot) + '.point').read_text()
                send('\x18\x01')
                send('\t', .5)
                self.assertEqual(inspect_line(), 'printf 中文')
                self.assertEqual(pathlib.Path(str(snapshot) + '.point').read_text(), point)
                send('\t')
                send('\x1b', .5)

                # Resize while the popup is active, then resume native editing.
                send('\x01\x0bprintf ' + 'x' * 130)
                send('\x18\x01')
                for columns in (48, 120, 72):
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 20, columns, 0, 0))
                    os.killpg(proc.pid, signal.SIGWINCH)
                    pump(.4)
                send('\t', .5)
                self.assertEqual(inspect_line(), 'printf ' + 'x' * 130)
                send('\t')
                send('\x1b', .5)
                self.assertEqual(inspect_line(), 'printf ' + 'x' * 130)

                # Enter is interpreted by Bash after Tab, with real shell state.
                confirmed = f'printf RUNOK > {folder}/executed'
                send('\x01\x0b' + confirmed)
                send('\x18\x01')
                send('\t', .5)
                send('\r', .5)
                self.assertEqual((folder / 'executed').read_text(), 'RUNOK')
                self.assertEqual(inspect_line(), '')
                self.assertEqual((folder / 'bindings').read_text(), bindings_before)
                # Normal Bash history contains the actual command, not eval.
                send(f'history 2 > {folder}/history\r')
                self.assertIn(confirmed, (folder / 'history').read_text())
                self.assertIn(b'\x1b[J', transcript)
                self.assertNotIn(b'\x1b[>1u', transcript)
            finally:
                proc.kill()
                proc.wait(timeout=3)
                os.close(master)
