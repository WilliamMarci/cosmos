"""IME routing and cursor-anchored two-row presentation; pane drafts stay local."""

import asyncio
from textual.dom import NoScreen
from textual.widgets import Input

from cosmos_tui.core.controller import Controller
from cosmos_tui.features.ime.rime import Rime
from cosmos_tui.features.ime.layout import compose
from cosmos_tui.ui.cell_surface import CellSurface
from cosmos_tui.ui.editor import CellEditor
from cosmos_tui.ui.cells import Rect
from cosmos_tui.ui.zones import Zone

KEYS = dict(
    enter=0xFF0D,
    escape=0xFF1B,
    backspace=0xFF08,
    delete=0xFFFF,
    left=0xFF51,
    up=0xFF52,
    right=0xFF53,
    down=0xFF54,
    home=0xFF50,
    end=0xFF57,
    pageup=0xFF55,
    pagedown=0xFF56,
    space=32,
)


class IMEController(Controller):
    def __init__(self, app):
        super().__init__(app)
        self.enabled = False
        self.full = False
        self.engine = None
        self.surface = None
        self.owner = "cosmos.ime"
        self.starting = False

    def status(self):
        return ("中" if self.enabled else "En") + " " + ("●" if self.full else "◐")

    async def toggle(self):
        if self.starting:
            return
        if self.engine is None:
            self.starting = True
            try:
                self.engine = await asyncio.to_thread(Rime)
            except (OSError, RuntimeError) as error:
                await self.app.action_error("input method", error)
                return
            finally:
                self.starting = False
        self.enabled = not self.enabled
        await self.refresh()

    async def toggle_width(self):
        self.full = not self.full
        await self.refresh()

    def target(self):
        app = self.app
        focus = app.screen.focused
        if isinstance(focus, CellEditor) and not focus.disabled and not focus.read_only:
            pane = app.screen.source() if hasattr(app.screen, "source") else None
            return ("input", focus), focus.cursor_screen_offset, pane
        if isinstance(focus, Input) and not focus.disabled and not focus.password:
            return ("input", focus), focus.cursor_screen_offset, None
        pane = app.active()
        if (
            app.screen is app._workspace_screen
            and pane
            and not pane.viewer
            and not pane.copy_mode
            and app.view_focus is None
        ):
            return (
                ("pane", pane.id),
                (pane.x + pane.cursor[0], pane.y + pane.cursor[1]),
                pane,
            )
        return None, None, None

    async def handle(self, event):
        if event.is_forwarded or self.starting:
            return False
        target, _, _ = self.target()
        if target is None:
            return False
        character = event.character
        if not self.enabled:
            if (
                self.full
                and character
                and len(character) == 1
                and 0x20 <= ord(character) <= 0x7E
                and not event.key.startswith(("ctrl+", "alt+", "meta+"))
            ):
                await self.commit(
                    target, "　" if character == " " else chr(ord(character) + 0xFEE0)
                )
                return True
            return False
        key = KEYS.get(event.key)
        if (
            key is None
            and character
            and len(character) == 1
            and character.isascii()
            and character.isprintable()
            and not event.key.startswith(("ctrl+", "alt+", "meta+"))
        ):
            key = ord(character)
        if key is None:
            return False
        before = self.engine.context(target)["preedit"]
        if not before and key >= 0xFF00:
            return False
        handled, text = self.engine.process(target, key, self.full)
        if text:
            await self.commit(target, text)
        await self.refresh()
        return handled

    async def commit(self, target, text):
        if target != self.target()[0]:
            return
        if target[0] == "input":
            target[1].insert_text_at_cursor(text)
        else:
            await self.app.backend.paste(text, target=target[1])

    async def refresh(self):
        app = self.app
        target, cursor, pane = self.target()
        context = (
            self.engine.context(target)
            if self.enabled and self.engine and target
            else None
        )
        if not context or not context["preedit"]:
            if self.surface:
                self.surface.display = False
            return
        # Textual can retain is_mounted after a screen subtree was detached.
        # Its screen property then raises instead of returning the old screen.
        try:
            attached = self.surface is not None and self.surface.screen is app.screen
        except NoScreen:
            attached = False
        if not attached:
            if self.surface:
                if self.surface.is_mounted:
                    await self.surface.remove()
                app.ui_registry.detach(self.owner)
            app.ui_registry.attach(self.owner, Zone.INSERT_COVER, self.click)
            self.surface = CellSurface(app.ui_registry, self.owner)
            self.surface.styles.layer = "ime"
            await app.screen.mount(self.surface)
        area = (
            Rect(pane.x, pane.y, pane.width, pane.height)
            if pane
            else Rect(
                0,
                0,
                app.size.width,
                app.size.height - int(app.query_one("#status").display),
            )
        )
        self.surface.display = True
        self.surface.present(
            compose(
                context,
                area,
                cursor,
                app.role_colors,
                app.settings.get("ime_number_style", "normal"),
            )
        )

    def click(self, action):
        self.app.run_worker(self.choose(action))

    async def choose(self, action):
        target = self.target()[0]
        if self.engine and target:
            _, text = self.engine.process(
                target, KEYS[action] if action in KEYS else ord(action), self.full
            )
            if text:
                await self.commit(target, text)
            await self.refresh()

    def close(self):
        if self.engine:
            self.engine.close()
            self.engine = None
        if self.owner in self.app.ui_registry.surfaces:
            self.app.ui_registry.detach(self.owner)
