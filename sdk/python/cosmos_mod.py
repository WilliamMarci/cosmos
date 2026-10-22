"""Small standard-library client for trusted Cosmos Mods (protocol v1)."""
import json
import os
import socket

MAX_MESSAGE = 1024 * 1024

class Cosmos:
    def __init__(self, path=None):
        self.path = path or os.environ['COSMOS_CONTROL_SOCKET']
        self.owner = os.environ.get('COSMOS_MOD_ID')

    def call(self, method, params=None):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5)
            connection.connect(self.path)
            with connection.makefile('rwb') as stream:
                result = None
                for index, operation, arguments in (
                    (0, 'initialize', {'protocol_major': 1}),
                    (1, method, {} if params is None else params),
                ):
                    body = json.dumps({'jsonrpc': '2.0', 'id': index,
                                       'method': operation, 'params': arguments}).encode() + b'\n'
                    if len(body) > MAX_MESSAGE:
                        raise ValueError('request too large')
                    stream.write(body)
                    stream.flush()
                    line = stream.readline(MAX_MESSAGE + 1)
                    if not line.endswith(b'\n') or len(line) > MAX_MESSAGE:
                        raise RuntimeError('invalid or oversized response')
                    reply = json.loads(line)
                    if reply.get('id') != index:
                        raise RuntimeError('response ID mismatch')
                    if 'error' in reply:
                        raise RuntimeError(reply['error']['message'])
                    result = reply['result']
                return result

    def ready(self):
        return self.call('mods.ready', {'id': self.owner,
                                       'token': os.environ['COSMOS_MOD_TOKEN']})

    def notify(self, text, actionable=False, actions=None, *, level="info", ttl_ms=None, persistent=False, session_id=None):
        return self.call('notifications.publish', {'text': text, 'source': self.owner,
                                                  'actionable': actionable, 'actions': actions or [], 'level': level,
                                                  'ttl_ms': ttl_ms, 'persistent': persistent, 'session_id': session_id})

    def publish(self, topic, data):
        return self.call('events.publish', {'owner': self.owner,
                                           'topic': f'mod.{self.owner}.{topic}', 'data': data})

    def register_manifest(self, manifest):
        """Register trusted program actions and launcher metadata (absolute cwd)."""
        return self.call('mods.register', manifest)

    def actions(self):
        """Discover registered actions, placements, UI contexts and launchability."""
        return self.call('actions.list')


class StatusWidget:
    """A client-local, non-modal status component; Mod lifecycle releases it."""
    def __init__(self, api, client):
        self.api, self.client = api, client
        self.view = api.call('presentation.open', {'client':client,'kind':'status_widget','owner':api.owner})

    def update(self, text, role='mute'):
        self.view = self.api.call('presentation.update', {'client':self.client,'view':self.view['id'],
            'owner':self.api.owner,'revision':self.view['revision'],
            'content':{'lines':[{'text':text,'role':role}]}})

    def close(self):
        return self.api.call('presentation.close', {'client':self.client,'view':self.view['id'],'owner':self.api.owner})
