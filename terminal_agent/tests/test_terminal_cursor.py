"""Optional real-emulator cursor regression: TA_TEST_TMUX=1 runs a private tmux."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('TA_TEST_TMUX') == '1' and shutil.which('tmux'),
                     'opt in with TA_TEST_TMUX=1 (requires a private Unix socket)')
class TerminalCursorTests(unittest.TestCase):
    def test_physical_cursor_round_trip(self):
        with tempfile.TemporaryDirectory(prefix='ta-cursor-') as temporary:
            folder = Path(temporary)
            rc = folder / 'bashrc'
            rc.write_text(f"PS1='top line\\n\\[\\e[36m\\]TEST> \\[\\e[0m\\]'\n"
                          f'HISTFILE=/dev/null\nsource {ROOT}/shell/agent.bash\n')
            base = ['tmux', '-S', str(folder / 'socket'), '-f', '/dev/null']

            def tmux(*args):
                return subprocess.check_output(base + list(args), text=True)

            def keys(*args):
                tmux('send-keys', *args)
                time.sleep(.15)

            def cursor():
                return tmux('display-message', '-p', '#{cursor_x} #{cursor_y}').strip()

            def pane():
                return tmux('capture-pane', '-p')

            command = shlex.join(['env', 'XDG_RUNTIME_DIR=' + temporary,
                                  'TERMINAL_AGENT_DEMO=1',
                                  'TERMINAL_AGENT_PYTHON=' + sys.executable,
                                  'bash', '--noprofile', '--rcfile', str(rc), '-i'])
            try:
                tmux('new-session', '-d', '-x', '100', '-y', '24', command)
                tmux('set-option', '-g', 'status', 'off')
                time.sleep(.4)
                for text, moves in [('printf 中文abcdef', 3), ('x' * 230, 120),
                                    ('x' * 94, 94), ('x' * 95, 95)]:
                    with self.subTest(length=len(text), cursor=moves):
                        keys('C-a', 'C-k')
                        keys('-l', text)
                        keys('C-a', *(['C-f'] * moves))
                        before_cursor, before_pane = cursor(), pane()
                        keys('C-x', 'C-a')
                        time.sleep(.3)
                        keys('-l', 'draft 中文')
                        keys('Tab')
                        time.sleep(.3)
                        self.assertEqual(cursor(), before_cursor)
                        self.assertIn('draft 中文', pane())
                        self.assertEqual(pane().count('○'), 1)
                        without_bar = '\n'.join(line for line in pane().splitlines() if '○' not in line)
                        self.assertEqual(without_bar.rstrip(), before_pane.rstrip())
                        keys('-l', 'Z')
                        self.assertEqual(pane().count('○'), 1)
                        keys('BSpace')
                        self.assertEqual(cursor(), before_cursor)
                        self.assertEqual(pane().count('○'), 1)
                        keys('Tab')
                        time.sleep(.3)
                        keys('Escape')
                        time.sleep(.3)
                        self.assertEqual(cursor(), before_cursor)
                        self.assertEqual(pane(), before_pane)
                # Window reflow must place the physical cursor at the Unicode
                # buffer's cell offset, rather than its UTF-8 byte offset.
                keys('C-a', 'C-k')
                keys('-l', 'printf ' + '中' * 30 + 'x' * 60)
                keys('C-a', *(['C-f'] * 50))
                # At width 48 a two-cell Chinese glyph wraps before the last
                # single cell, leaving one padding cell: the column is 39.
                for width, expected_x in ((48, 39), (120, 86)):
                    keys('C-x', 'C-a')
                    time.sleep(.3)
                    tmux('resize-window', '-x', str(width), '-y', '24')
                    time.sleep(.4)
                    keys('Tab')
                    time.sleep(.3)
                    self.assertEqual(int(cursor().split()[0]), expected_x, pane())
                    self.assertEqual(pane().count('TEST>'), 1, pane())
                    self.assertGreaterEqual(tmux('capture-pane', '-p', '-S', '-').count('top line'), 1)
                keys('Tab')
                time.sleep(.3)
                keys('Escape')
                time.sleep(.3)
                self.assertEqual(int(cursor().split()[0]), 86)
                # Submitted requests survive child-process replacement and Tab.
                keys('C-x', 'C-a')
                time.sleep(.3)
                for request in ('first request', 'second request'):
                    keys('-l', request)
                    keys('Enter')
                    time.sleep(.8)
                keys('-l', 'draft request')
                for key, expected in [('Up', 'second request'), ('Up', 'first request'),
                                      ('Down', 'second request'), ('Down', 'draft request')]:
                    keys(key)
                    self.assertIn(expected, pane())
                keys('Tab')
                time.sleep(.3)
                self.assertIn('draft request', pane())
                keys('Tab')
                time.sleep(.3)
                keys('Up')
                self.assertIn('second request', pane())
                keys('Escape')
                time.sleep(.3)
                self.assertNotIn('○', pane())
                # The visible inactive bar follows native-editor resize too.
                keys('C-a', 'C-k')
                keys('-l', 'echo hi')
                keys('C-x', 'C-a')
                time.sleep(.3)
                keys('-l', 'still here')
                keys('Tab')
                time.sleep(.3)
                for width in (60, 100):
                    tmux('resize-window', '-x', str(width), '-y', '24')
                    time.sleep(.4)
                    self.assertIn('echo hi', pane())
                    self.assertEqual(pane().count('○'), 1, pane())
                    self.assertEqual(int(cursor().split()[0]), 13, pane())
                keys('Tab')
                time.sleep(.3)
                keys('Escape')
                time.sleep(.3)
                self.assertNotIn('○', pane())


            finally:
                subprocess.run(base + ['kill-server'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
