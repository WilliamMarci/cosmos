#!/usr/bin/env python3
"""Launch from the Cosmos Mods menu to open an interactive, Cosmos-rendered view."""
from pathlib import Path
import os
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdk/python'))
from cosmos_mod import Cosmos

client = Cosmos()
target = os.environ.get('COSMOS_CLIENT_ID')
if not target:
    raise SystemExit('Launch this Mod from the Cosmos panel; a target client is required.')
client.ready()
view = client.call('presentation.open', {'client': target, 'kind': 'help', 'owner': client.owner})
revision = view['revision']
count = 0

def paint():
    global revision
    updated = client.call('presentation.update', {
        'client': target, 'view': view['id'], 'owner': client.owner, 'revision': revision,
        'content': {'title': 'Cosmos Mod surface', 'lines': [
            {'text': 'Rendered by Cosmos; no Tmux drawing commands.', 'role': 'fg'},
            {'text': 'Type to send keys to this view. Esc returns.', 'role': 'mute'},
            {'text': f'Received keys: {count}', 'role': 'ok'},
        ]}})
    revision = updated['revision']

paint()
while True:
    try:
        keys = client.call('presentation.read_input', {'client': target, 'view': view['id'], 'owner': client.owner})
        if keys:
            count += len(keys)
            paint()
        time.sleep(0.05)
    except RuntimeError as error:
        if 'unknown view' in str(error) or 'unknown client' in str(error):
            break
        raise
