import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import subprocess
import unittest
from unittest.mock import patch

from cosmos_tui.core import updater


class UpdateTests(unittest.TestCase):
    def test_selects_published_version_and_preserves_prefix_style(self):
        releases = [dict(tag_name='v0.2.2', draft=False, published_at='now'), dict(tag_name='v9.0.0', draft=True, published_at=None)]
        self.assertEqual(updater.release_version(releases), '0.2.2')
        self.assertEqual(updater.next_prefix(Path('/apps/0.2.1'), '0.2.1', '0.2.2'), Path('/apps/0.2.2'))
        self.assertEqual(updater.next_prefix(Path('/apps/custom'), '0.2.1', '0.2.2'), Path('/apps/custom-0.2.2'))

    def test_unchanged_payload_reuses_files_but_modified_payload_downloads(self):
        installer = updater.installer_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, bundle, temporary = root/'old', root/'bundle', root/'downloads'
            for p in (old/'bin', old/'licenses/opencode', bundle, temporary):p.mkdir(parents=True)
            (old/'bin/cosmos-agent').write_bytes(b'unchanged')
            (old/'licenses/opencode/LICENSE').write_text('MIT')
            digest, paths = installer.installed_payload(old, 'agent')
            self.assertEqual(len(paths), 2)
            filename = 'agent.tar.gz'
            content = b'new archive'
            entry = dict(name='agent', arch=os.uname().machine, glibc_min='2.28', cpu_flags=[], filename=filename, url='https://github.com/WilliamMarci/cosmos/releases/download/v0.2.2/'+filename, payload_sha256=digest, sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            with patch.object(installer, 'download', side_effect=AssertionError('Redundant download')):
                result, _ = installer.component(bundle, 'agent', '0.2.2', temporary, dict(components=[entry]), old)
                self.assertIsInstance(result, installer.ReusedComponent)
            (old/'bin/cosmos-agent').write_bytes(b'modified')
            with patch.object(installer, 'download', side_effect=lambda url,path,limit:path.write_bytes(content)) as download:
                result, _ = installer.component(bundle, 'agent', '0.2.2', temporary, dict(components=[entry]), old)
                self.assertIsInstance(result, Path)
                download.assert_called_once()

    def test_download_reports_bytes_and_completion(self):
        installer = updater.installer_module()
        with tempfile.TemporaryDirectory() as folder:
            response = io.BytesIO(b'x'*1024**2)
            response.headers = {'Content-Length': str(1024**2)}
            output = io.StringIO()
            with patch.object(installer.urllib.request, 'urlopen', return_value=response), contextlib.redirect_stderr(output):
                installer.download('https://example.invalid/component', Path(folder)/'component', 1024**2)
            self.assertIn('(0%)', output.getvalue())
            self.assertIn('(100%)', output.getvalue())
            self.assertIn('done', output.getvalue())

    def test_up_to_date_does_not_launch_installer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'installed-features.json').write_text(json.dumps(dict(version='0.2.1', features=['core'])))
            installer=updater.installer_module()
            with patch.object(updater, 'PROJECT_ROOT', root), patch.object(updater, 'installer_module', return_value=installer), patch.dict(os.environ, {'XDG_CACHE_HOME': folder}), patch.object(installer, 'download', side_effect=lambda url,path,limit:path.write_text(json.dumps([dict(tag_name='v0.2.1', draft=False, published_at='now')]))), patch.object(updater.subprocess, 'run') as run:
                updater.update()
                run.assert_not_called()

    def test_reuse_install_switches_entry_only_after_success(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as folder:
                installer = updater.installer_module()
                root = Path(folder)
                old, bundle, prefix, bindir = (root/n for n in ('old','bundle','new','commands'))
                for path in (old/'bin',old/'licenses/opencode',bundle,bindir):path.mkdir(parents=True)
                (old/'bin/cosmos-agent').write_bytes(b'original agent')
                (old/'licenses/opencode/LICENSE').write_text('MIT')
                (old/'cosmos').write_text('old launcher')
                (old/'installed-features.json').write_text('{}')
                command=bindir/'cosmos';command.symlink_to(old/'cosmos')
                (bundle/'cosmos').write_text('new launcher')
                (bundle/'bundle.json').write_text(json.dumps(dict(version='0.2.2',glibc='2.28')))
                digest,_=installer.installed_payload(old,'agent')
                entry=dict(name='agent', arch=os.uname().machine,glibc_min='2.28',cpu_flags=[],filename='agent.tar.gz',url='https://github.com/WilliamMarci/cosmos/releases/download/v0.2.2/agent.tar.gz',payload_sha256=digest)
                (bundle/'components.json').write_text(json.dumps(dict(version='0.2.2',components=[entry])))
                def runtime_check(argv,**kwargs):
                    if fail and argv[0]==str(prefix/'cosmos'):
                        raise subprocess.CalledProcessError(1,argv)
                with patch.object(installer.os,'getuid',return_value=1000),patch.object(installer.os,'confstr',return_value='glibc 2.28'),patch.object(installer,'verify'),patch.object(installer,'download',side_effect=AssertionError('Unchanged component downloaded')),patch.object(installer.subprocess,'run',side_effect=runtime_check),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    args=['--bundle',str(bundle),'--prefix',str(prefix),'--bin-dir',str(bindir),'--reuse-from',str(old),'--features','core,agent','--yes']
                    if fail:
                        with self.assertRaises(subprocess.CalledProcessError):installer.main(args)
                    else:installer.main(args)
                self.assertEqual(command.resolve(),(old if fail else prefix)/'cosmos')
                self.assertEqual((old/'bin/cosmos-agent').read_bytes(),b'original agent')
                if fail:self.assertFalse(prefix.exists())
                else:self.assertEqual((prefix/'bin/cosmos-agent').read_bytes(),b'original agent')

    def test_unsafe_core_archive_never_runs_installer_or_switches_entry(self):
        installer = updater.installer_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current, commands = root/'0.2.1', root/'bin'
            current.mkdir(); commands.mkdir()
            (current/'cosmos').write_text('old launcher')
            (current/'installed-features.json').write_text(json.dumps(dict(version='0.2.1',features=['core'],bin_dir=str(commands))))
            command = commands/'cosmos'; command.symlink_to(current/'cosmos')
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w:gz') as tar:
                member = tarfile.TarInfo('../escape'); member.size=1
                tar.addfile(member,io.BytesIO(b'x'))
            data = stream.getvalue()
            filename='cosmos-0.2.2-core-linux-x86_64-glibc2.28.tar.gz'
            entry=dict(name='core',arch=os.uname().machine,glibc_min='2.28',cpu_flags=[],filename=filename,url='https://github.com/WilliamMarci/cosmos/releases/download/v0.2.2/'+filename,size=len(data),sha256=hashlib.sha256(data).hexdigest())
            def fetch(url,path,limit):
                if path.name=='releases.json':path.write_text(json.dumps([dict(tag_name='v0.2.2',published_at='now',draft=False)]))
                elif path.name=='components.json':path.write_text(json.dumps(dict(version='0.2.2',components=[entry])))
                else:path.write_bytes(data)
            with patch.object(updater,'PROJECT_ROOT',current),patch.object(updater,'installer_module',return_value=installer),patch.dict(os.environ,{'XDG_CACHE_HOME':folder}),patch.object(installer,'download',side_effect=fetch),patch.object(updater.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError,'Unsafe update archive root'):updater.update()
                run.assert_not_called()
            self.assertEqual(command.resolve(),current/'cosmos')
            self.assertFalse((root/'escape').exists())
