"""Deployment boundaries: offline selection, terminal capabilities and host isolation."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging'))
import installer
from elf import patch_private_elfs
from cosmos_tui.core.paths import display_path


class DeploymentTests(unittest.TestCase):
    def test_connect_feedback_precedes_headers_and_failed_download_retries(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'partial'
            path.write_bytes(b'partial')
            def fail(*args, **kwargs):
                self.assertIn('Connect', output.getvalue())
                raise urllib.error.URLError('timed out')
            with patch.object(installer.urllib.request, 'urlopen', side_effect=fail) as connect, patch.object(installer.time, 'sleep'), contextlib.redirect_stderr(output):
                with self.assertRaisesRegex(OSError, '--offline --package-dir'):
                    installer.download('https://example.invalid/components.json', path, 1024)
            self.assertEqual(connect.call_count, 3)
            self.assertFalse(path.exists())
            self.assertIn('3/3', output.getvalue())

    def test_offline_component_prefers_existing_lower_compatible_tier(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = b'local archive'
            entries = [dict(name='pdf', arch=os.uname().machine, glibc_min=tier, cpu_flags=[], filename='pdf-'+tier+'.tar.gz', url='https://github.com/WilliamMarci/cosmos/releases/download/v0.2.2/pdf-'+tier+'.tar.gz', size=len(data), sha256=hashlib.sha256(data).hexdigest()) for tier in ('2.28','2.34')]
            (root / entries[0]['filename']).write_bytes(data)
            with patch.object(installer.os, 'confstr', return_value='glibc 2.34'), patch.object(installer, 'download', side_effect=AssertionError('offline network')):
                path, entry = installer.component(root,'pdf','0.2.2',root,dict(components=entries),package_dir=root,offline=True)
                self.assertEqual(entry['glibc_min'],'2.28')
                path.unlink()
                with self.assertRaisesRegex(ValueError,'Offline package missing'):
                    installer.component(root,'pdf','0.2.2',root,dict(components=entries),package_dir=root,offline=True)

    def test_offline_bootstrap_never_calls_network_and_selects_local_core(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); tools = root/'tools'; tools.mkdir()
            for name, script in {'getconf':'echo "glibc 2.34"', 'curl':'exit 97', 'wget':'exit 98'}.items():
                path=tools/name;path.write_text('#!/bin/sh\n'+script+'\n');path.chmod(0o755)
            name='cosmos-0.2.3-core-linux-x86_64-glibc2.28'
            archive=root/(name+'.tar.gz')
            payload=b'#!/bin/bash\nprintf "local-core-228\\n"\n'
            with tarfile.open(archive,'w:gz') as tar:
                item=tarfile.TarInfo(name+'/install.sh');item.size=len(payload);item.mode=0o755
                tar.addfile(item,io.BytesIO(payload))
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            lines=[]
            for tier in ('2.28','2.34'):
                filename=f'cosmos-0.2.3-core-linux-x86_64-glibc{tier}.tar.gz'
                lines.append('\t'.join(['core','0.2.3','x86_64',tier,'sse4_2',filename,'https://github.com/WilliamMarci/cosmos/releases/download/v0.2.3/'+filename,digest,'1','1']))
            (root/'components.tsv').write_text('\n'.join(lines)+'\n')
            env={**os.environ,'PATH':str(tools)+':'+os.environ['PATH'],'XDG_CACHE_HOME':str(root/'cache')}
            result=subprocess.run(['bash',str(ROOT/'packaging/bootstrap.sh'),'--offline','--package-dir',str(root),'--yes'],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('local-core-228',result.stdout)
            self.assertNotIn('Connect/download:',result.stdout)

    def test_home_abbreviation_is_dynamic_boundary_aware_and_resolves_aliases(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'home';home.mkdir();alias=root/'alias';alias.symlink_to(home,target_is_directory=True)
            with patch.dict(os.environ,{'HOME':str(alias)}):
                self.assertEqual(display_path(str(alias)),'~')
                self.assertEqual(display_path(str(home/'child')),'~/child')
                self.assertEqual(display_path(str(root/'home2')) ,str(root/'home2'))
            with patch.dict(os.environ,{'HOME':str(root/'home2')}):
                self.assertEqual(display_path(str(home)),str(home))

    def test_launcher_keeps_private_loader_environment_out_of_children(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for relative in ('python/cosmos_tui','.venv/bin','bin','share/terminfo'):(root/relative).mkdir(parents=True)
            shutil.copy2(ROOT/'cosmos',root/'cosmos')
            (root/'.venv/bin/python').symlink_to(sys.executable)
            (root/'python/cosmos_tui/__init__.py').write_text('')
            (root/'python/cosmos_tui/__main__.py').write_text('import json,os; print(json.dumps(dict(os.environ)))')
            probe=root/'bin/infocmp';probe.write_text('#!/bin/sh\ncase "$*" in *xterm-kitty*) exit 1;; *) exit 0;; esac\n');probe.chmod(0o755)
            env={**os.environ,'TERM':'xterm-kitty','LD_LIBRARY_PATH':'/root-sdk:/conda-sdk','PYTHONHOME':'/conda-sdk','PYTHONPATH':'/root-python'}
            env.pop('TEXTUAL_COLOR_SYSTEM',None);env.pop('COSMOS_HOST_ENV_ACTIVE',None);env.pop('COSMOS_OUTER_TERM',None)
            result=subprocess.run(['bash',str(root/'cosmos')],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            child=json.loads(result.stdout)
            self.assertNotIn('LD_LIBRARY_PATH',child)
            self.assertNotIn('PYTHONHOME',child)
            self.assertEqual(child['COSMOS_HOST_LD_LIBRARY_PATH'],'/root-sdk:/conda-sdk')
            self.assertEqual(child['TERM'],'xterm-256color')
            self.assertEqual(child['COSMOS_OUTER_TERM'],'xterm-kitty')
            self.assertEqual(child['TEXTUAL_COLOR_SYSTEM'],'truecolor')
            self.assertEqual(child['COLORTERM'],'truecolor')
            env['TEXTUAL_COLOR_SYSTEM']='256'
            result=subprocess.run(['bash',str(root/'cosmos')],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(json.loads(result.stdout)['TEXTUAL_COLOR_SYSTEM'],'256')

    def test_shell_restores_host_then_deduplicates_root_conda_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.bashrc').write_text('export LD_LIBRARY_PATH="/root-sdk:/conda-sdk:${LD_LIBRARY_PATH}"\n')
            rc=root/'empty';rc.write_text('')
            env={**os.environ,'HOME':str(root),'COSMOS_RC':str(rc),'COSMOS_HOST_ENV_ACTIVE':'1','COSMOS_HOST_LD_LIBRARY_PATH_SET':'1','COSMOS_HOST_LD_LIBRARY_PATH':'/root-sdk:/conda-sdk','COSMOS_HOST_PATH_SET':'1','COSMOS_HOST_PATH':os.environ['PATH']}
            env.pop('LD_LIBRARY_PATH',None)
            result=subprocess.run(['bash','--noprofile','--norc','-c','source "$1"; printf "%s" "$LD_LIBRARY_PATH"','test',str(ROOT/'shell/cosmos.bash')],env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'/root-sdk:/conda-sdk')

    @unittest.skipUnless(shutil.which('cc') and shutil.which('patchelf'),'ELF build tools unavailable')
    def test_rpath_wins_over_host_library_without_exporting_private_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'app';host=root/'host'
            for path in (stage/'lib',stage/'bin',host):path.mkdir(parents=True)
            source=root/'value.c';main=root/'main.c';main.write_text('#include <stdio.h>\nint value(void); int main(void){printf("%d\\n",value());}\n')
            for directory,value in ((stage/'lib',42),(host,99)):
                source.write_text(f'int value(void){{return {value};}}')
                subprocess.run(['cc','-shared','-fPIC',str(source),'-o',str(directory/'libprobe.so')],check=True)
            binary=stage/'bin/probe'
            subprocess.run(['cc',str(main),'-L'+str(stage/'lib'),'-lprobe','-o',str(binary)],check=True)
            patch_private_elfs(stage)
            result=subprocess.run([str(binary)],env={**os.environ,'LD_LIBRARY_PATH':str(host)},text=True,capture_output=True,check=True)
            self.assertEqual(result.stdout.strip(),'42')
            tags=subprocess.check_output(['readelf','-d',str(binary)],text=True)
            self.assertIn('(RPATH)',tags)
            self.assertNotIn('(RUNPATH)',tags)

    @unittest.skipUnless(shutil.which('tic') and shutil.which('infocmp'),'terminfo build tools unavailable')
    def test_bundled_terminfo_works_without_host_database(self):
        spec=importlib.util.spec_from_file_location('deployment_assemble',ROOT/'packaging/assemble.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'closure'):
            root=Path(folder)
            module.bundle_terminfo(root)
            env={**os.environ,'HOME':str(root),'TERMINFO':str(root/'missing'),'TERMINFO_DIRS':str(root/'share/terminfo')}
            result=subprocess.run([str(root/'bin/infocmp'),'-x','xterm-256color'],env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
