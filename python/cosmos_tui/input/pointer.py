from __future__ import annotations

import logging

from cosmos_tui.core.controller import Controller
from cosmos_tui.input import mouse_protocol
from cosmos_tui.render.surface import TerminalSurface


class PointerRouter(Controller):
    def __init__(self, app):
        super().__init__(app)
        self.press = None

    def pane_at(self, event):
        return next(
            (
                pane
                for pane in self.app.panes
                if pane.x <= event.screen_x < pane.x + pane.width
                and pane.y <= event.screen_y < pane.y + pane.height
            ),
            None,
        )

    @staticmethod
    def inside(pane, event):
        return (
            pane.x <= event.screen_x < pane.x + pane.width
            and pane.y <= event.screen_y < pane.y + pane.height
        )

    def forwardable(self, pane):
        app = self.app
        return bool(
            pane
            and app.settings.get("mouse_passthrough", True)
            and app.screen is app._workspace_screen
            and not app.views
            and not pane.viewer
            and not pane.copy_mode
            and pane.mouse_any
        )

    async def send(self, pane, button, event, *, release=False, motion=False):
        from cosmos_tui.features.agent.control import human_input

        await human_input(self.app, pane)
        x = event.screen_x - pane.x + 1
        y = event.screen_y - pane.y + 1
        data = mouse_protocol.encode(
            pane,
            button,
            max(1, min(pane.width, x)),
            max(1, min(pane.height, y)),
            release=release,
            motion=motion,
            modifier_bits=mouse_protocol.modifiers(event),
        )
        if data is None:
            return False
        try:
            await self.app.backend.send_bytes(pane.id, data)
        except RuntimeError as error:
            await self.app.action_error("mouse passthrough", error)
            return False
        event.stop()
        return True

    async def on_mouse_down(self, event):
        app = self.app
        if app.screen is app._workspace_screen:
            target = self.pane_at(event)
            if target is None and event.button in (1, 2, 3):
                header = next(
                    (
                        pane
                        for pane in app.panes
                        if pane.id in getattr(app, "_agent_headers", {})
                        and event.screen_y == pane.y - 1
                        and pane.x <= event.screen_x < pane.x + pane.width
                    ),
                    None,
                )
                if header:
                    from cosmos_tui.features.agent.control import human_input

                    await human_input(app, header)
                    event.stop()
                    return
            if target and event.button == 1 and not target.active:
                await app.backend.request(f"select-pane -t {target.id}")
                app.panes = await app.backend.snapshot()
                app.query_one(TerminalSurface).focus()
                target = next((p for p in app.panes if p.id == target.id), target)
                logging.getLogger(__name__).debug("mouse focus %s", target.id)
            if target and event.button in (1, 2, 3) and self.forwardable(target):
                button = event.button - 1
                if await self.send(target, button, event):
                    self.press = (target.id, button)
        await app.reader_ui.on_mouse_down(event)

    async def on_mouse_move(self, event):
        app = self.app
        await app.reader_ui.on_mouse_move(event)
        if not self.press or app.reader_ui.drag:
            return
        pane = next((p for p in app.panes if p.id == self.press[0]), None)
        if (
            pane
            and self.forwardable(pane)
            and mouse_protocol.accepts_motion(pane)
            and self.inside(pane, event)
        ):
            await self.send(pane, self.press[1], event, motion=True)

    async def on_mouse_up(self, event):
        app = self.app
        app.reader_ui.on_mouse_up(event)
        if not self.press:
            return
        pane_id, button = self.press
        self.press = None
        pane = next((p for p in app.panes if p.id == pane_id), None)
        if pane and self.forwardable(pane):
            await self.send(pane, button, event, release=True)

    async def on_mouse_scroll_up(self, event):
        app = self.app
        if app.reader_ui.viewer_at(event):
            await app.reader_ui.scroll_viewer(event, -1)
            return
        pane = self.pane_at(event)
        if self.forwardable(pane):
            await self.send(pane, mouse_protocol.WHEEL_UP, event)
            return
        await app.history_ui.scroll_history(event, True)

    async def on_mouse_scroll_down(self, event):
        app = self.app
        if app.reader_ui.viewer_at(event):
            await app.reader_ui.scroll_viewer(event, 1)
            return
        pane = self.pane_at(event)
        if self.forwardable(pane):
            await self.send(pane, mouse_protocol.WHEEL_DOWN, event)
            return
        await app.history_ui.scroll_history(event, False)
