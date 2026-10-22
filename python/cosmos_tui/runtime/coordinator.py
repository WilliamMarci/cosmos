from __future__ import annotations

import logging

from rich.text import Text
from textual.geometry import Offset
from textual.widgets import Static

from cosmos_tui.core import rpc
from cosmos_tui.core.controller import Controller
from cosmos_tui.features.notifications.toast import NoticeToast
from cosmos_tui.render.ansi import decode_grid
from cosmos_tui.render.graphics import Batch
from cosmos_tui.render.surface import TerminalSurface
from cosmos_tui.ui.chrome import Frame
from cosmos_tui.ui.styles import DARK, LIGHT
from cosmos_tui.features.theme.controller import apply_interface


class RuntimeController(Controller):
    async def on_mount(self):
        app = self.app
        app._workspace_screen = app.screen
        await app.assistant_ui.start()
        await app.backend.connect()
        await rpc.call(
            "ui.attach",
            {
                "client": app.client,
                "width": max(1, app.size.width),
                "height": max(1, app.size.height),
            },
        )
        app.query_one("#agent-powerline").display = False
        app.query_one(TerminalSurface).focus()
        app.set_interval(0.1, app.tick)
        await self.tick()

    async def on_unmount(self):
        app = self.app
        await app.reader_ui.close()
        app.ime.close()
        await app.assistant_ui.close()
        await app.backend.close()
        try:
            await rpc.call("ui.detach", {"client": app.client})
        except (OSError, RuntimeError):
            pass

    async def tick(self):
        app = self.app
        if app.busy or app.closing:
            return
        app.busy = True
        try:
            await rpc.call("ui.heartbeat", {"client": app.client})
            app.settings = await rpc.call("settings.get")
            app.role_colors = LIGHT if app.settings["theme"] == "light" else DARK
            apply_interface(app)
            for frame in app.screen.query(Frame):
                frame.apply_theme(app.role_colors)
            terminal = app.query_one(TerminalSurface)
            status_widget = app.query_one("#status", Static)
            if status_widget.display != app.settings["status_visible"]:
                status_widget.display = app.settings["status_visible"]
            await app.backend.resize(
                max(1, terminal.size.width), max(1, terminal.size.height)
            )
            panes = await app.backend.snapshot()
            lines = {}
            images = []
            snapshot = await rpc.call("ui.snapshot", {"client": app.client})
            app.views = []
            app.status_widgets = []
            app.view_focus = None
            for layer in snapshot.get("views", []):
                view = layer["view"]
                if view["kind"] == "status_widget":
                    app.status_widgets.append(view)
                    continue
                if view["owner"] == "core":
                    continue
                target = view.get("target")
                if target:
                    pane = next((p for p in panes if p.id == target), None)
                    if pane is None:
                        continue
                    layer["rect"] = {
                        "x": pane.x,
                        "y": pane.y,
                        "width": pane.width,
                        "height": pane.height,
                    }
                app.views.append(layer)
                if snapshot.get("focus") == view["id"] and (
                    not target or any(p.id == target and p.active for p in panes)
                ):
                    app.view_focus = view["id"]

            reader_visible = app.screen is app._workspace_screen or getattr(
                app.screen, "preserve_workspace_graphics", False
            )
            app.reader_ui.sync_visible(panes)
            for pane in panes:
                lines[pane.id] = list(decode_grid(tuple(pane.lines)))
                if pane.viewer:
                    try:
                        frame = app.reader_ui.loading.frame(pane)
                        lines[pane.id] = frame.lines
                        if reader_visible and not app.views:
                            cover = getattr(app.screen, "cover_reader_image", None)
                            image = cover(frame.image, pane) if cover else frame.image
                            images.append((pane.id, image, pane.x, pane.y))
                    except Exception as error:
                        frame = app.reader_ui.loading.placeholder(pane, str(error))
                        lines[pane.id] = frame.lines
                        app.message = str(error)
            if app.search is not None:
                app.message = "/" + app.search
            app.panes, app.lines = panes, lines
            if getattr(app.screen, "bounds", None) is not None and getattr(
                app.screen, "preserve_workspace_graphics", False
            ):
                app.screen.place()
            await app.assistant_ui.refresh(panes, terminal)
            notices = await rpc.call("notifications.active", {"client": app.client})
            for host in (app._workspace_screen, app.screen):
                if host:
                    for notice in host.query(NoticeToast):
                        notice.present_notices(
                            notices,
                            app.size.width,
                            app.size.height,
                            app.role_colors,
                            status_rows=int(app.settings.get("status_visible", True)),
                            pane_width=app.active().width
                            if app.active()
                            else app.size.width,
                        )
            covers = [
                run.rect
                for notice in app.screen.query(NoticeToast)
                if notice.display and notice.frame
                for run in notice.frame.runs
                if not run.text
            ]
            images = [
                (
                    key,
                    app.graphics.cover(
                        key,
                        image,
                        x,
                        y,
                        app.reader_ui.cell_pixels(),
                        covers,
                        app.role_colors["base"],
                    ),
                    x,
                    y,
                )
                for key, image, x, y in images
            ]
            app.graphics.commit(
                images if app.graphics.enabled and reader_visible else []
            )
            surface_state = (
                [(p.id, p.x, p.y, p.width, p.height, p.active) for p in panes],
                lines,
                app.views,
                app.role_colors,
                app.settings.get("terminal_theme", "inherit"),
            )
            if surface_state != app._surface_state:
                app._surface_state = surface_state
                terminal.refresh()
            if app.graphics.pending:
                app.call_after_refresh(app.flush_graphics)
            await app.status.refresh()
            await app.ime.refresh()
            pane = app.active()
            # Modal inputs own the physical cursor. Polling a hidden shell must not
            # relocate its cursor into the switcher / restart input cursor painting.
            if pane and app.screen is app._workspace_screen:
                position = Offset(pane.x + pane.cursor[0], pane.y + pane.cursor[1])
                if app.cursor_position != position:
                    app.cursor_position = position
                    if not app.is_headless:
                        app._display(app.screen, Batch())
            if not app.is_headless and app.cursor_mode() != app._cursor_mode:
                app._display(app.screen, Batch())
        except EOFError:
            await self.detach("exit")
        except Exception as error:
            logging.getLogger(__name__).exception("UI refresh failed")
            app.message = str(error)
            status = Text(app.message, style="red")
            if status != app._status_content:
                app._status_content = status
                app.query_one("#status", Static).update(status)
        finally:
            app.busy = False

    async def detach(self, reason="detach"):
        app = self.app
        app.closing = True
        app.graphics.commit([])
        app.flush_graphics()
        await app.backend.close()
        try:
            await rpc.call("ui.detach", {"client": app.client})
        except (OSError, RuntimeError):
            pass
        app.exit({"reason": reason, "session": app.backend.session})

    async def action_error(self, command, error, *, session_id=None):
        app = self.app
        # A rejected user operation is not a fatal frontend exception.
        text = " ".join(str(error).split())[:240] or "Operation failed"
        logging.getLogger(__name__).warning("operation %s failed: %s", command, text)
        app.message = text
        try:
            await rpc.call(
                "notifications.publish",
                {
                    "text": text,
                    "source": "workspace",
                    "ttl_ms": 5000,
                    "level": "error",
                    "session_id": session_id
                    if session_id is not None
                    else getattr(app.backend, "session_id", None),
                },
            )
        except (OSError, RuntimeError):
            logging.getLogger(__name__).warning("could not publish operation error")
