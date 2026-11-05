"""Destructive lifecycle operations must prove ownership and preserve other Tmux."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cosmos_tui.terminal import backend
from cosmos_tui.core import lifecycle
from cosmos_tui.core.uninstall import uninstall


class LifecycleTests(unittest.TestCase):
    def test_identity_mismatch_refuses_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / 'server.json'
            expected = dict(pid=123, start='10', uid=os.getuid(), executable='/bin/tmux', socket='/tmp/fake')
            record.write_text(json.dumps(expected))
            record.chmod(0o600)
            with patch.object(backend, 'probe', return_value=dict(expected, start='11')):
                with self.assertRaisesRegex(PermissionError, 'identity changed'):
                    backend.verified(record)

    def test_noninteractive_stop_requires_explicit_confirmation(self):
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Confirmation requires'):
                lifecycle.confirm()

    def test_source_tree_cannot_be_uninstalled(self):
        with self.assertRaisesRegex(ValueError, 'marked release'):
            uninstall(yes=True)

    @unittest.skipUnless(os.getenv('COSMOS_TEST_TMUX') and shutil.which(backend.executable()), 'isolated Tmux integration')
    def test_owned_backend_shutdown_preserves_unrelated_server(self):
        with tempfile.TemporaryDirectory(prefix='cosmos-lifecycle-') as folder:
            root = Path(folder)
            env = dict(XDG_STATE_HOME=str(root/'state'), XDG_RUNTIME_DIR=str(root/'runtime'), COSMOS_TASKS_HOME=str(root/'tasks'), COSMOS_TMUX_SOCKET=root.name)
            with patch.dict(os.environ, env):
                own = backend.command()
                other = backend.command(root.name+'-other')
                def run(argv, *args):
                    return subprocess.run([*argv,*args],check=True,capture_output=True,text=True,timeout=5)
                try:
                    run(own,'-f','/dev/null','new-session','-d','-s','owned','sleep 60')
                    run(other,'-f','/dev/null','new-session','-d','-s','unrelated','sleep 60')
                    backend.record(created_server=True)
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        lifecycle.stop_all(yes=True, coordinator=False)
                    self.assertIn('owned',output.getvalue())
                    self.assertIsNone(backend.probe(own))
                    self.assertIsNotNone(backend.probe(other))
                    self.assertFalse(list(backend.records_dir().glob('*.json')))
                finally:
                    for argv in (own,other):
                        subprocess.run([*argv,'kill-server'],capture_output=True,timeout=5)

    def test_uninstall_removes_only_its_own_entry_and_retains_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'app';root.mkdir()
            entrydir = Path(folder)/'bin';entrydir.mkdir()
            (root/'installed-features.json').write_text(json.dumps(dict(bin_dir=str(entrydir))))
            (root/'cosmos').write_text('launcher')
            entry = entrydir/'cosmos';entry.symlink_to(root/'cosmos')
            data = Path(folder)/'user-data';data.write_text('keep')
            with patch('cosmos_tui.core.uninstall.PROJECT_ROOT',root), patch('cosmos_tui.core.uninstall.processes',return_value=[]), patch.object(lifecycle,'inventory',return_value=[]), contextlib.redirect_stdout(io.StringIO()):
                uninstall(yes=True)
            self.assertFalse(root.exists())
            self.assertFalse(entry.is_symlink())
            self.assertEqual(data.read_text(),'keep')
