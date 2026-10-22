"""Backend contract: propose(history) -> command; interactive(command) -> argv."""
import asyncio
import json
import os
import re
import signal
from pathlib import Path
from .storage import Storage


class OpenCode:
    def __init__(self, config):
        self.config = config
        self.storage = Storage(config)

    def environment(self):
        env = os.environ.copy()
        if not self.config['inherit_opencode']:
            # Keep credentials available, but isolate provider/project settings.
            env['OPENCODE_CONFIG_DIR'] = self.config.get('opencode_config_dir', os.path.expanduser('~/.config/terminal-agent/opencode'))
            env['OPENCODE_DISABLE_PROJECT_CONFIG'] = 'true'
        # Generation is read-only, including when a user's default agent has tools.
        overlay = json.loads(env.get('OPENCODE_CONFIG_CONTENT', '{}'))
        overlay['permission'] = {'*': 'deny'}
        overlay['tools'] = {'bash': False, 'write': False, 'edit': False, 'task': False}
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps(overlay)
        env.update(self.storage.environment())
        env['OPENCODE_DISABLE_FILEWATCHER'] = 'true'
        return env

    def prompt(self, history, cwd=None):
        prompt = ('Translate the request into one shell command for the current working directory. '
                  'Do not execute commands or use tools. Return ONLY a JSON object with one string key "command". '
                  'Use the previous command and follow-up requests as context. Do not invent filenames; use globs or discovery. '
                  'Actual target working directory (the generated command will run here): '
                  + json.dumps(str(Path(cwd) if cwd else Path.cwd())) + '. Request history: ' + json.dumps(history, ensure_ascii=False))
        if self.config.get('prompt_file'):
            prompt = Path(self.config['prompt_file']).read_text() + '\n\n' + prompt
        return prompt

    async def propose(self, history, cwd=None):
        prompt = self.prompt(history,cwd)
        argv = [self.config['executable'], 'run', '--standalone', '--format', 'json']
        model = self.model(cwd)
        if model:
            argv += ['--model', model]
        self.storage.prepare(inherit_auth=self.config.get('inherit_opencode', True))
        environment = self.environment()
        environment['PWD'] = str(self.storage.workspace)
        if self.config.get('inherit_opencode', True) and model:
            for name, value in self.storage.inherited_environment(model.split('/', 1)[0]).items():
                environment.setdefault(name, value)
        process = await asyncio.create_subprocess_exec(*argv, prompt, env=environment, cwd=self.storage.workspace,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self.config['timeout'])
        except BaseException:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
            raise
        output = stdout.decode(errors='replace')
        if process.returncode:
            # OpenCode emits provider/auth failures as JSON on stdout, even
            # when stderr is empty. Surface the real reason instead of a stub.
            for line in output.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'error':
                    raise RuntimeError(error_message(event.get('error', {})))
            raise RuntimeError(stderr.decode(errors='replace')[-600:] or f'OpenCode exited with status {process.returncode}')
        return parse_events(output)

    def model(self, target=None):
        if self.config.get('model'):
            return self.config['model']
        if not self.config.get('inherit_opencode', True):
            return ''
        # Preserve an explicit OpenCode model before using the TUI's recent model.
        # Do not print config/auth contents or copy credentials into this project.
        content = json.loads(os.environ.get('OPENCODE_CONFIG_CONTENT', '{}'))
        if isinstance(content.get('model'), str) and content['model']:
            return content['model']
        candidates = []
        cwd = Path(target) if target else Path.cwd()
        for directory in (cwd, *cwd.parents):
            candidates.extend(directory / name for name in ('opencode.jsonc', 'opencode.json'))
        config_root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'opencode'
        candidates.extend(config_root / name for name in ('opencode.jsonc', 'opencode.json'))
        if os.environ.get('OPENCODE_CONFIG'):
            candidates.insert(0, Path(os.environ['OPENCODE_CONFIG']))
        for path in candidates:
            data = read_jsonc(path)
            if isinstance(data.get('model'), str) and data['model']:
                return data['model']
        state_root = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
        data = read_jsonc(state_root / 'opencode/model.json')
        recent = data.get('recent', [])
        if isinstance(recent, list) and recent and isinstance(recent[0], dict) and all(isinstance(recent[0].get(k), str) for k in ('providerID', 'modelID')):
            return recent[0]['providerID'] + '/' + recent[0]['modelID']
        return ''

    def interactive(self, command):
        argv = [self.config['executable']]
        if command:
            argv += ['--prompt', 'Help me review and complete this command: ' + command]
        return argv


def parse_events(raw):
    parts = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'error':
            raise RuntimeError(error_message(event.get('error', {})))
        if event.get('type') == 'text':
            parts.append(event.get('part', {}).get('text', ''))
    if not parts:
        raise RuntimeError('OpenCode returned no command; check the selected model and authentication')
    result = json.loads(''.join(parts))
    command = result.get('command')
    if not isinstance(command, str) or not command.strip() or '\n' in command or '\r' in command or any(ord(c) < 32 for c in command):
        raise ValueError('Backend must return a nonempty single-line command')
    return command


def error_message(error):
    if isinstance(error, dict):
        return str(error.get('message') or error.get('data', {}).get('message') or error.get('type') or 'OpenCode error')[:600]
    return str(error)[:600]


def read_jsonc(path):
    try:
        raw = path.read_text()
        # Preserve quoted strings while removing JSONC comments and trailing commas.
        raw = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                     lambda match: match[0] if match[0].startswith('"') else '', raw, flags=re.S)
        raw = re.sub(r',(?=\s*[}\]])', '', raw)
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class Demo:
    async def propose(self, history):
        await asyncio.sleep(0.15)
        return "magick '*.png' images.pdf"

    def interactive(self, command):
        return ['printf', '%s\\n', 'Demo: real agent mode uses OpenCode.']
