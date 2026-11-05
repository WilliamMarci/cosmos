"""Run against an installed release, not the source environment; no model calls."""
import os,pathlib,subprocess,tempfile,time,sys,json,shlex
from types import SimpleNamespace
app=pathlib.Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='cosmos-helper-proof-') as tmp:
 root=pathlib.Path(tmp);(root/'home').mkdir();(root/'run').mkdir(mode=0o700)
 env={**os.environ,'HOME':str(root/'home'),'XDG_RUNTIME_DIR':str(root/'run'),'XDG_STATE_HOME':str(root/'state'),'XDG_CONFIG_HOME':str(root/'config'),'COSMOS_TMUX_SOCKET':root.name,'TERMINAL_AGENT_DEMO':'1','PYTHONHOME':'/invalid/conda','PYTHONPATH':'/invalid/host','COSMOS_PYTHON':'/invalid/conda/python','TERMINAL_AGENT_PYTHON':'/invalid/conda/python','TERM':'xterm-256color'}
 backend=[str(app/'bin/cosmos-tmux'),'-L',root.name]
 def run(args):return subprocess.run(args,env=env,capture_output=True,text=True,check=True,timeout=8).stdout
 try:
  run([str(app/'cosmos'),'new','-d','-s','fixture'])
  run([*backend,'send-keys','-t','fixture','C-x','C-a'])
  found=False
  for _ in range(60):
   for folder in pathlib.Path('/proc').glob('[0-9]*'):
    try:
     args=(folder/'cmdline').read_bytes().split(b'\0')
     if b'terminal_agent.cli' in args and str(app).encode() in args[0]:
      assert b'-I' in args,args;found=True
    except (OSError,IndexError):pass
   if found:break
   time.sleep(.05)
  assert found,run([*backend,'capture-pane','-p','-S','-','-t','fixture'])
  run([*backend,'send-keys','-t','fixture','Escape'])
  print('Real packaged Bash pane helper uses private venv -I despite poisoned host Python: OK')
  assert not (app/'python-deps').exists()
  for toolset in ('terminal','actions'):
   messages=[dict(jsonrpc='2.0',id=1,method='initialize',params={}),dict(jsonrpc='2.0',id=2,method='tools/list',params={})]
   result=subprocess.run([str(app/'.venv/bin/python'),'-I','-m','cosmos_tui.features.agent','mcp','--socket',root.name,'--toolset',toolset],env=env,input=''.join(json.dumps(m)+'\n' for m in messages),capture_output=True,text=True,check=True,timeout=10)
   replies=[json.loads(line) for line in result.stdout.splitlines()]
   assert len(replies)==2 and replies[-1]['result']['tools'],result.stdout
  print('Installed terminal/actions MCP imports and JSON-RPC handshake: OK')
  if '--agent' in sys.argv:
   from cosmos_tui.features.agent.launch import arguments
   pane=run([*backend,'display-message','-p','-t','fixture','#{pane_id}']).strip()
   command=arguments(SimpleNamespace(argv=backend),pane)
   target=run([*backend,'new-window','-d','-P','-F','#{pane_id}','-t','fixture','sleep 30']).strip()
   run([*backend,'set-option','-p','-t',target,'remain-on-exit','failed'])
   run([*backend,'respawn-pane','-k','-t',target,shlex.join(command)])
   output=''
   for _ in range(100):
    output=run([*backend,'capture-pane','-p','-S','-','-t',target])
    if 'deepseek' in output.lower() and 'Cosmos' in output:break
    time.sleep(.1)
   assert 'deepseek' in output.lower() and 'Cosmos' in output,output
   print('Installed Cosmos Agent rendered in its own pane with inherited host proxy: OK')
 finally:subprocess.run([*backend,'kill-server'],env=env,capture_output=True,timeout=5)
