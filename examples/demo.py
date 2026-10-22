#!/usr/bin/env python3
"""Ready handshake, notification and settings-event demonstration."""
from pathlib import Path
import signal
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdk/python'))
from cosmos_mod import Cosmos

stopping = False

def stop(_signal, _frame):
    global stopping
    stopping = True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
client = Cosmos()
client.ready()
client.notify('Demo Mod ready')
snapshot = client.call('state.snapshot')
cursor = snapshot['cursor']
client.publish('ready', {'protocol': 1})
while not stopping:
    page = client.call('events.poll', {'after': cursor, 'epoch': snapshot['epoch'],
                                      'wait_ms': 200, 'topics': ['settings.changed']})
    if page['gap']:
        snapshot = client.call('state.snapshot')
        cursor = snapshot['cursor']
        continue
    cursor = page['cursor']
    for event in page['events']:
        client.publish('theme', {'theme': event['data']['theme']})
