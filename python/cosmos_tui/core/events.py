"""Bounded client event journal for deterministic UI lifecycle consumers."""

import asyncio
from collections import deque


class ClientEvents:
    def __init__(self, capacity=256):
        self.records = deque(maxlen=capacity)
        self.sequence = 0
        self.changed = asyncio.Event()

    def publish(self, topic, data):
        self.sequence += 1
        event = dict(seq=self.sequence, topic=topic, data=dict(data))
        self.records.append(event)
        previous, self.changed = self.changed, asyncio.Event()
        previous.set()
        return event
