import errno
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerTUITests(unittest.TestCase):
    def test_user_can_edit_install_and_command_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'runtime/bin').mkdir(parents=True)
            (root/'runtime/bin/python3').symlink_to(sys.executable)
            (root/'bundle.json').write_text(json.dumps(dict(version='0.2.2')))
            (root/'installer.py').write_text('import json,sys; print("ARGS="+json.dumps(sys.argv[1:]))\n')
            shutil.copy2(ROOT/'packaging/install.sh',root/'install.sh')
            master, slave = pty.openpty()
            process = subprocess.Popen(['bash',str(root/'install.sh')],stdin=slave,stdout=slave,stderr=slave)
            os.close(slave)
            prefix = str(root/'software with spaces')
            command = str(root/'commands')
            os.write(master, f'p\n{prefix}\nb\n{command}\n\n'.encode())
            output = bytearray()
            deadline = time.monotonic()+10
            try:
                while time.monotonic()<deadline:
                    if select.select([master],[],[],0.1)[0]:
                        try:
                            chunk=os.read(master,65536)
                            if not chunk:break
                            output.extend(chunk)
                        except OSError as error:
                            if error.errno==errno.EIO:break
                            raise
                    if process.poll() is not None:break
                self.assertEqual(process.wait(timeout=1),0,output.decode())
                marker=output.decode().rsplit('ARGS=',1)[1].strip()
                args=json.loads(marker)
                self.assertEqual(args[args.index('--prefix')+1],prefix)
                self.assertEqual(args[args.index('--bin-dir')+1],command)
            finally:
                if process.poll() is None:process.kill();process.wait()
                os.close(master)
