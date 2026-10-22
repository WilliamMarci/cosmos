"""Application state is separate from the target working directory and OpenCode."""
import json
import os
import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, config):
        state_home = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
        cache_home = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
        data_home = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
        self.root = Path(config.get('state_dir') or state_home / 'terminal-agent').expanduser()
        self.cache = cache_home / 'terminal-agent/opencode'
        self.data = self.root / 'opencode-data'
        self.opencode_state = self.root / 'opencode-state'
        self.workspace = self.root / 'backend-workspace'
        self.auth_source = data_home / 'opencode/auth.json'
        self.database_source = data_home / 'opencode/opencode.db'

    @staticmethod
    def private_directory(path):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise RuntimeError('Application storage must be a directory owned by the current user')
        path.chmod(0o700)

    def prepare(self, inherit_auth=True):
        for path in (self.root, self.cache, self.data, self.opencode_state, self.workspace,
                     self.data / 'opencode'):
            self.private_directory(path)
        auth = self.data / 'opencode/auth.json'
        # Reuse authentication without copying secrets. All databases, logs and
        # snapshots remain in this application's private namespace.
        if inherit_auth and self.auth_source.exists() and not os.path.lexists(auth):
            try:
                auth.symlink_to(self.auth_source)
            except FileExistsError:
                pass

    def inherited_environment(self, provider):
        """Read v2 provider credentials without copying its database or sessions.

        Model metadata is public and may be cached. API credentials are passed
        only in the child process environment, never written to our config.
        """
        result = {}
        if not self.database_source.exists():
            return result  # Older OpenCode uses the auth.json reference.
        connection = None
        try:
            connection = sqlite3.connect(self.database_source.as_uri() + '?mode=ro', uri=True)
            row = connection.execute("SELECT value FROM kv WHERE key='models-dev:catalog'").fetchone()
            if not row:
                return result
            wrapper = json.loads(row[0])
            body = wrapper.get('body', wrapper)
            catalog = json.loads(body) if isinstance(body, str) else body
            metadata = catalog.get(provider, {})
            model_path = self.root / 'models.json'
            temporary = self.root / ('models.' + str(os.getpid()) + '.tmp')
            temporary.write_text(json.dumps(catalog))
            temporary.replace(model_path)
            result['OPENCODE_MODELS_PATH'] = str(model_path)
            env_names = metadata.get('env', [])
            row = connection.execute(
                'SELECT value FROM credential WHERE integration_id=? '
                'ORDER BY time_updated DESC LIMIT 1', (provider,)).fetchone()
            if row and env_names:
                credential = json.loads(row[0])
                key = credential.get('key')
                if isinstance(key, str) and key:
                    result[env_names[0]] = key
            return result
        except (sqlite3.Error, OSError, ValueError, AttributeError, TypeError):
            return result
        finally:
            if connection:
                connection.close()

    def environment(self):
        return {'XDG_DATA_HOME': str(self.data), 'XDG_STATE_HOME': str(self.opencode_state),
                'XDG_CACHE_HOME': str(self.cache)}

    def save_session(self, session_id, context):
        directory = self.root / 'sessions'
        self.private_directory(self.root)
        self.private_directory(directory)
        target = directory / (session_id + '.json')
        temporary = target.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(context, output, ensure_ascii=False)
        temporary.replace(target)
