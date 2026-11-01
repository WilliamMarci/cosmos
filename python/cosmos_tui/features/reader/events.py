"""Reader lifecycle events from actual loading, independent of Agent transport."""

import asyncio
from collections import OrderedDict
import secrets

from cosmos_tui.core.events import ClientEvents


class ReaderEvents:
    def __init__(self, app):
        if not hasattr(app, "client_events"):
            app.client_events = ClientEvents()
        self.bus = app.client_events
        self.requests = OrderedDict()

    def begin(self, pane, path):
        self.replaced(pane.id, None)
        request = secrets.token_hex(16)
        record = dict(request_id=request, pane=pane.id, path=path, wire=pane.viewer)
        self.requests[request] = record
        self.emit(record, "loading")
        while len(self.requests) > 128:
            self.requests.popitem(last=False)
        return request

    def emit(self, record, status, error=None):
        record["event"] = self.bus.publish(
            "reader." + status,
            dict(
                request_id=record["request_id"],
                pane=record["pane"],
                path=record["path"],
                status=status,
                error=error,
            ),
        )

    def replaced(self, pane, wire):
        for record in self.requests.values():
            if (
                record["pane"] == pane
                and record["wire"] != wire
                and record["event"]["data"]["status"] == "loading"
            ):
                self.emit(record, "superseded")

    def finish(self, pane, wire, status, error=None):
        for record in self.requests.values():
            if (
                record["pane"] == pane
                and record["wire"] == wire
                and record["event"]["data"]["status"] == "loading"
            ):
                self.emit(record, status, error)

    async def result(self, request, wait_ms=0):
        if type(wait_ms) is not int or not 0 <= wait_ms <= 2000:
            raise ValueError("wait_ms must be 0–2000")
        record = self.requests.get(request)
        if record is None:
            raise ValueError("Reader request is unknown or expired")
        deadline = asyncio.get_running_loop().time() + wait_ms / 1000
        while record["event"]["data"]["status"] == "loading":
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            changed = self.bus.changed
            try:
                await asyncio.wait_for(changed.wait(), remaining)
            except TimeoutError:
                break
        return record["event"]
