"""IME routing and cursor-anchored two-row presentation; pane drafts stay local."""

import asyncio
from textual.widgets import Input

from cosmos_tui.core.controller import Controller
from cosmos_tui.features.ime.rime import Rime
from cosmos_tui.ui.cell_surface import CellSurface
from cosmos_tui.ui.cells import CellRun, HitRegion, Rect, UIFrame, cell_width, clip
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
        return (
            ("中" if self.enabled else "英") + " " + ("全角" if self.full else "半角")
        )

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
        if (
            self.surface is None
            or not self.surface.is_mounted
            or self.surface.screen is not app.screen
        ):
            if self.surface:
                if self.surface.is_mounted:
                    await self.surface.remove()
                app.ui_registry.detach(self.owner)
            app.ui_registry.attach(self.owner, Zone.INSERT_COVER, self.click)
            self.surface = CellSurface(app.ui_registry, self.owner)
            self.surface.styles.layer = "ime"
            await app.screen.mount(self.surface)
        palette = app.role_colors
        candidates = context["candidates"]
        first = context["preedit"] + " ▏"
        labels = [f" {i + 1} {text} " for i, text in enumerate(candidates)]
        left, top = (pane.x, pane.y) if pane else (0, 0)
        available = pane.width if pane else app.size.width
        bottom = (
            pane.y + pane.height
            if pane
            else app.size.height - int(app.query_one("#status").display)
        )
        width = min(available, max(12, cell_width(first), sum(map(cell_width, labels))))
        height = min(2, bottom - top)
        x = max(left, min(cursor[0], left + available - width))
        y = (
            cursor[1] + 1
            if cursor[1] + 1 + height <= bottom
            else max(top, cursor[1] - height)
        )
        runs = [
            CellRun(
                Rect(x, y, width),
                clip(first, width).ljust(width),
                palette["accl"],
                palette["base"],
            )
        ]
        hits = []
        if height == 2:
            runs.append(
                CellRun(
                    Rect(x, y + 1, width), " " * width, palette["fg"], palette["base"]
                )
            )
            offset = 0
            for i, label in enumerate(labels):
                text = clip(label, width - offset)
                size = cell_width(text)
                if not size:
                    break
                selected = i == context["selected"]
                rect = Rect(x + offset, y + 1, size)
                runs.append(
                    CellRun(
                        rect,
                        text,
                        palette["on"] if selected else palette["fg"],
                        palette["acc"] if selected else palette["base"],
                        selected,
                    )
                )
                hits.append(HitRegion(str(i + 1), rect))
                offset += size
        self.surface.display = True
        self.surface.present(
            UIFrame(Rect(x, y, width, height), tuple(runs), tuple(hits))
        )

    def click(self, action):
        self.app.run_worker(self.choose(action))

    async def choose(self, action):
        target = self.target()[0]
        if self.engine and target:
            _, text = self.engine.process(target, ord(action), self.full)
            if text:
                await self.commit(target, text)
            await self.refresh()

    def close(self):
        if self.engine:
            self.engine.close()
            self.engine = None
        if self.owner in self.app.ui_registry.surfaces:
            self.app.ui_registry.detach(self.owner)
