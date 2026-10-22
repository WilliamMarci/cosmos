#!/usr/bin/env python3
"""Runnable Mod: a real status widget and service-synchronized choice notice."""
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sdk/python'))
from cosmos_mod import Cosmos, StatusWidget

api=Cosmos()
client=os.environ.get('COSMOS_CLIENT_ID')
if not client:
    raise SystemExit('Start this Mod from the Cosmos Mods menu with a source client.')
api.ready()
widget=StatusWidget(api,client)
widget.update('UI demo',role='mute')
notification=api.notify('Demo choice',actions=[{'id':'yes','label':'yes'},{'id':'no','label':'no'}])
after=0
while True:
    page=api.call('events.poll',{'after':after,'wait_ms':2000,'topics':['notifications.action']})
    after=page['cursor']
    # Recovery is authoritative in persisted notification state, including gaps.
    notices=api.call('notifications.list',{'client':client})
    notice=next((n for n in notices if n['id']==notification['id']),None)
    if notice and notice.get('selected_action'):
        widget.update('Picked '+notice['selected_action'],role='acc')
        break
# Preserve the component until the user stops the Mod; no redraw polling.
while True:
    page=api.call('events.poll',{'after':after,'wait_ms':2000,'topics':['service.stopped']})
    after=page['cursor']
