"""Private interpreter layout and visible Agent startup failures."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cosmos_tui.core.paths import python_command
from cosmos_tui.core.services import SessionWindows
from cosmos_tui.terminal.tmux import Tmux


class InterpreterTests(unittest.TestCase):
    def test_installed_interpreter_ignores_host_python_configuration(self):
        import cosmos_tui.core.paths as paths
        with tempfile.TemporaryDirectory() as folder, patch.object(paths,'PROJECT_ROOT',Path(folder)):
            (Path(folder)/'installed-features.json').write_text('{}')
            self.assertEqual(python_command('-m','cosmos_tui'),[str(Path(folder)/'.venv/bin/python'),'-I','-m','cosmos_tui'])

    def test_agent_proxy_bypass_preserves_external_proxies(self):
        from cosmos_tui.features.agent.launch import environment
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,HOME=folder,XDG_CONFIG_HOME=folder+'/config',XDG_RUNTIME_DIR=folder+'/run',HTTP_PROXY='http://proxy.invalid:3128',NO_PROXY='example.org',no_proxy='internal.invalid'):
                env=environment('proxy-fixture','%0')
                self.assertEqual(env['HTTP_PROXY'],'http://proxy.invalid:3128')
                self.assertEqual(set(env['NO_PROXY'].split(',')),{'example.org','internal.invalid','localhost','127.0.0.1','::1'})
                self.assertEqual(env['NO_PROXY'],env['no_proxy'])


@unittest.skipUnless(os.getenv('COSMOS_TEST_TMUX'),'isolated Tmux integration')
class AgentPaneTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_startup_failure_is_retained_with_error_output(self):
        with tempfile.TemporaryDirectory(prefix='cosmos-agent-failure-') as folder:
            with patch.dict(os.environ,HOME=folder,COSMOS_TMUX_SOCKET=Path(folder).name,XDG_STATE_HOME=folder+'/state',XDG_RUNTIME_DIR=folder+'/run',COSMOS_RC='/dev/null'):
                backend=Tmux('fixture')
                await backend.connect()
                try:
                    source=(await backend.snapshot())[0]
                    await SessionWindows(backend).split(source.id,[sys.executable,'-c','import sys;print("Agent startup fixture failed",flush=True);sys.exit(7)'],retain_failure=True)
                    for _ in range(40):
                        rows=await backend.cli('list-panes','-s','-F','#{pane_id}\t#{pane_dead}\t#{pane_dead_status}')
                        dead=[r.split('\t') for r in rows.splitlines() if '\t1\t7' in r]
                        if dead:break
                        await asyncio.sleep(.05)
                    self.assertTrue(dead,rows)
                    output=await backend.cli('capture-pane','-p','-S','-','-t',dead[0][0])
                    self.assertIn('Agent startup fixture failed',output)
                    window=await SessionWindows(backend).open([sys.executable,'-c','import sys;print("Agent window fixture failed",flush=True);sys.exit(7)'],retain_failure=True)
                    self.assertTrue(window.startswith('@'))
                    for _ in range(40):
                        output=await backend.cli('capture-pane','-p','-S','-','-t',window)
                        if 'Agent window fixture failed' in output:break
                        await asyncio.sleep(.05)
                    self.assertIn('Agent window fixture failed',output)
                finally:
                    await backend.close()
                    await backend.cli('kill-server')
