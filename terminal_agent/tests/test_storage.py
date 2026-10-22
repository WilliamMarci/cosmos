import json
import os
from pathlib import Path
import tempfile
import sqlite3
from contextlib import closing
import unittest
from unittest.mock import patch
from terminal_agent.storage import Storage
from terminal_agent.backend import OpenCode, read_jsonc, parse_events


class StorageTests(unittest.TestCase):
    def test_private_data_and_auth_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data'),
                   'XDG_CACHE_HOME': str(root / 'cache')}
            auth = root / 'data/opencode/auth.json'
            auth.parent.mkdir(parents=True)
            auth.write_text('{}')
            with patch.dict(os.environ, env):
                store = Storage({})
                store.prepare()
                self.assertEqual(store.root, root / 'state/terminal-agent')
                self.assertEqual((store.data / 'opencode/auth.json').resolve(), auth)
                self.assertTrue((store.data / 'opencode/auth.json').is_symlink())
                self.assertNotEqual(store.environment()['XDG_DATA_HOME'], env['XDG_DATA_HOME'])
                store.save_session('session-test', {'working_directory': '/target', 'command': 'pwd'})
                context = store.root / 'sessions/session-test.json'
                self.assertEqual(context.stat().st_mode & 0o777, 0o600)
                self.assertEqual(context.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(json.loads(context.read_text())['command'], 'pwd')

    def test_recent_model_fallback_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / 'state/opencode/model.json'
            model.parent.mkdir(parents=True)
            model.write_text(json.dumps({'recent': [{'providerID': 'deepseek', 'modelID': 'deepseek-flash'}]}))
            env = {'XDG_CONFIG_HOME': str(root / 'config'), 'XDG_STATE_HOME': str(root / 'state'),
                   'OPENCODE_CONFIG_CONTENT': '{}', 'OPENCODE_CONFIG': ''}
            with patch.dict(os.environ, env), patch('pathlib.Path.cwd', return_value=root):
                self.assertEqual(OpenCode({'inherit_opencode': True}).model(), 'deepseek/deepseek-flash')
                self.assertEqual(OpenCode({'model': 'chosen/model'}).model(), 'chosen/model')
                config = root / 'opencode.jsonc'
                config.write_text('{/*config*/ "model": "project/model",}')
                self.assertEqual(OpenCode({'inherit_opencode': True}).model(), 'project/model')
                self.assertEqual(read_jsonc(config)['model'], 'project/model')

    def test_provider_message_is_visible(self):
        with self.assertRaisesRegex(RuntimeError, 'Authentication required'):
            parse_events(json.dumps({'type': 'error', 'error': {'type': 'provider.auth',
                'message': 'Authentication required', 'response': {'body': 'private response'}}}))


    def test_v2_auth_is_inherited_without_copying_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data'),
                   'XDG_CACHE_HOME': str(root / 'cache')}
            source = root / 'data/opencode/opencode.db'
            source.parent.mkdir(parents=True)
            with closing(sqlite3.connect(source)) as connection:
                connection.execute('CREATE TABLE kv (key TEXT, value TEXT)')
                catalog = {'deepseek': {'env': ['DEEPSEEK_API_KEY'], 'models': {}}}
                connection.execute('INSERT INTO kv VALUES (?,?)',
                    ('models-dev:catalog', json.dumps({'body': json.dumps(catalog)})))
                connection.execute('CREATE TABLE credential (integration_id TEXT, value TEXT, time_updated INT)')
                connection.execute('INSERT INTO credential VALUES (?,?,?)',
                    ('deepseek', json.dumps({'type': 'api', 'key': 'test-only-not-a-real-key'}), 1))
                connection.commit()
            with patch.dict(os.environ, env):
                store = Storage({})
                store.prepare()
                inherited = store.inherited_environment('deepseek')
                self.assertEqual(inherited['DEEPSEEK_API_KEY'], 'test-only-not-a-real-key')
                self.assertEqual(json.loads(Path(inherited['OPENCODE_MODELS_PATH']).read_text()), catalog)
                self.assertFalse((store.data / 'opencode/opencode.db').exists())
                for file in store.root.rglob('*'):
                    if file.is_file():
                        self.assertNotIn('test-only-not-a-real-key', file.read_text())
