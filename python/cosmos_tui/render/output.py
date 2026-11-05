from __future__ import annotations

from textual._compositor import CompositorUpdate

from cosmos_tui.core.controller import Controller
from cosmos_tui.render.graphics import Batch


class OutputController(Controller):
    def cursor_mode(self):
        app = self.app
        if app.closing:
            return (True, 0)
        pane = app.active()
        visible = bool(
            pane
            and app.screen is app._workspace_screen
            and not pane.viewer
            and not app.views
            and pane.cursor_visible
        )
        if not visible:
            return (False, 0)
        shape = pane.cursor_shape
        # Default follows the terminal's usual blinking block; explicit VT styles
        # from applications retain their steady/blinking choice.
        blinking = shape == "default" or pane.cursor_blinking
        style = {"block": 1, "underline": 3, "bar": 5}.get(shape, 1) + (not blinking)
        return (True, style)

    def _display(self, screen, renderable):
        app = self.app
        # Textual drops writes during a batch/startup. Retain graphics packets
        # until the driver can actually accept the compositor update.
        writable = (
            app._running
            and not app._closed
            and not app.is_headless
            and app._driver is not None
            and not app._batch_count
        )
        if not writable:
            return app._display_native(screen, renderable)
        if isinstance(renderable, CompositorUpdate):
            mode = self.cursor_mode()
            control = ""
            if mode != app._cursor_mode:
                visible, style = mode
                control = (
                    (
                        f"\x1b[{style} q"
                        + ("\x1b[?12h" if style % 2 or style == 0 else "\x1b[?12l")
                        + "\x1b[?25h"
                    )
                    if visible
                    else "\x1b[?25l"
                )
                if (
                    app._running
                    and not app._closed
                    and not app.is_headless
                    and app._driver is not None
                    and not app._batch_count
                ):
                    app._cursor_mode = mode
            renderable = Batch(renderable, app.graphics.take() + control)
        app._display_native(screen, renderable)

    def flush_graphics(self):
        app = self.app
        if app.graphics.pending and not app.is_headless:
            if not app._running:
                # Textual removes screens before Unmount, but closes its driver
                # afterwards. Flush final image deletions through that same owner.
                if app._driver is not None:
                    app._driver.write(app.graphics.take())
                    app._driver.flush()
                return
            self._display(app.screen, Batch())

    def on_resize(self, event):
        app = self.app
        pixels = event.pixel_size
        app.reader_ui.pixel_cell = (
            (
                max(1, round(pixels.width / event.size.width)),
                max(1, round(pixels.height / event.size.height)),
            )
            if pixels
            and pixels.width
            and pixels.height
            and event.size.width
            and event.size.height
            else None
        )
