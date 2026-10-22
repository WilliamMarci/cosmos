from __future__ import annotations

import logging

from cosmos_tui.core.controller import Controller
from cosmos_tui.render.surface import TerminalSurface


class PointerRouter(Controller):
    async def on_mouse_down(self, event):
        app = self.app
        if app.screen is app._workspace_screen and event.button == 1:
            target = next(
                (
                    p
                    for p in app.panes
                    if p.x <= event.screen_x < p.x + p.width
                    and p.y <= event.screen_y < p.y + p.height
                ),
                None,
            )
            if target and not target.active:
                await app.backend.request(f"select-pane -t {target.id}")
                app.panes = await app.backend.snapshot()
                app.query_one(TerminalSurface).focus()
                logging.getLogger(__name__).debug("mouse focus %s", target.id)
        await app.reader_ui.on_mouse_down(event)

    async def on_mouse_move(self, event):
        await self.app.reader_ui.on_mouse_move(event)

    def on_mouse_up(self, event):
        self.app.reader_ui.on_mouse_up(event)

    async def on_mouse_scroll_up(self, event):
        if self.app.reader_ui.viewer_at(event):
            await self.app.reader_ui.scroll_viewer(event, -1)
        else:
            await self.app.history_ui.scroll_history(event, True)

    async def on_mouse_scroll_down(self, event):
        if self.app.reader_ui.viewer_at(event):
            await self.app.reader_ui.scroll_viewer(event, 1)
        else:
            await self.app.history_ui.scroll_history(event, False)
