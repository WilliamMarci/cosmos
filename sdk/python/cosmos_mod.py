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

    def notify(self, text, actionable=False):
        return self.call('notifications.publish', {'text': text, 'source': self.owner,
                                                  'actionable': actionable})

    def publish(self, topic, data):
        return self.call('events.publish', {'owner': self.owner,
                                           'topic': f'mod.{self.owner}.{topic}', 'data': data})
