import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('bash'), 'requires Bash')
class ShellLoadingTests(unittest.TestCase):
    def load_from(self, directory, source, python=None):
        environment = dict(os.environ, CDPATH=str(directory))
        environment.pop('TERMINAL_AGENT_PYTHON', None)
        if python is not None:
            environment['TERMINAL_AGENT_PYTHON'] = python
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c', '''
cd() { printf 'unexpected cd function output'; builtin cd "$@"; }
source "$1" || exit $?
source "$1" || exit $?
printf '%s\\0%s\\0%s\\0' "$PWD" "$_TERMINAL_AGENT_ROOT" "$TERMINAL_AGENT_PYTHON"
''', 'loading-test', str(source)], cwd=directory, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        fields = result.stdout.decode().split('\0')
        self.assertEqual(fields[0], str(directory))
        self.assertEqual(fields[1], str(ROOT))
        self.assertTrue(os.path.isabs(fields[2]))
        self.assertTrue(os.access(fields[2], os.X_OK))
        self.assertEqual(fields[3:], [''])
        return fields[2]

    def test_absolute_source_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.load_from(Path(temporary), ROOT / 'shell/agent.bash')

    def test_relative_symlink_source_and_reload(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'agent.bash').symlink_to(ROOT / 'shell/agent.bash')
            self.load_from(directory, './agent.bash')
            relative_python = os.path.relpath(sys.executable, ROOT)
            resolved = self.load_from(directory, './agent.bash', python=relative_python)
            self.assertTrue(os.path.samefile(resolved, sys.executable))
