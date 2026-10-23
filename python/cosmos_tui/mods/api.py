"""Public in-process UI Mod API v1. No calendar-specific host logic."""

from textual.binding import Binding as Binding
from textual.widgets import Static as Static
from rich.text import Text as Text
from cosmos_tui.input.shortcuts import CosmosModal
from cosmos_tui.ui.chrome import Frame as Frame


class ModPopup(CosmosModal):
    mod_context = "mod_popup"
    preserve_workspace_graphics = True
    DEFAULT_CSS = "ModPopup { align: right bottom; padding: 0; background: transparent; background-tint: transparent; }"
    BINDINGS = [Binding("escape,q", "dismiss", show=False)]

    def reader_images(self, key, image, pane):
        """Clip graphic placements outside native UI cells, including backgrounds."""
        cw, ch = self.app.reader_ui.cell_pixels()
        boxes = tuple(
            (f.region.x - pane.x, f.region.y - pane.y, f.region.width, f.region.height)
            for f in self.query(Frame)
        )
        signature = (id(image), pane.x, pane.y, pane.width, pane.height, boxes, cw, ch)
        if getattr(self, "_tiles_key", None) == signature:
            return self._tiles
        regions = [(0, 0, pane.width, pane.height)]
        for bx, by, bw, bh in boxes:
            next_regions = []
            for x, y, w, h in regions:
                left, top, right, bottom = (
                    max(x, bx),
                    max(y, by),
                    min(x + w, bx + bw),
                    min(y + h, by + bh),
                )
                if left >= right or top >= bottom:
                    next_regions.append((x, y, w, h))
                    continue
                for rect in (
                    (x, y, w, top - y),
                    (x, bottom, w, y + h - bottom),
                    (x, top, left - x, bottom - top),
                    (right, top, x + w - right, bottom - top),
                ):
                    if rect[2] > 0 and rect[3] > 0:
                        next_regions.append(rect)
            regions = next_regions
        self._tiles = [
            (
                f"{key}:mod:{index}",
                image.crop((x * cw, y * ch, (x + w) * cw, (y + h) * ch)),
                pane.x + x,
                pane.y + y,
            )
            for index, (x, y, w, h) in enumerate(regions)
        ]
        self._tiles_key = signature
        return self._tiles

    def action_help(self):
        from cosmos_tui.ui.help import Help
        from cosmos_tui.input import keymap

        self.app.push_screen(
            Help("Mod shortcuts", keymap.help_rows(self.mod_context, self.app.settings))
        )


class ModAPI:
    def __init__(self, manager, ident):
        self._manager, self.id = manager, ident

    @property
    def palette(self):
        return dict(self._manager.app.role_colors)

    def commands(self, commands):
        from cosmos_tui.input import keymap

        for name, label, keys, target in commands:
            ident = f"mod.{self.id}.{name}"
            existing = next((c for c in keymap.COMMANDS if c.id == ident), None)
            if existing:
                keymap.COMMANDS.remove(existing)
            keymap.register(ident, "mod." + self.id, label, keys, target)

    def status_action(self, slot, callback):
        if slot not in ("clock",):
            raise ValueError("Unsupported status action slot")
        self._manager.register(self.id, slot, callback)

    def popup(self, screen):
        if self.id not in self._manager.loaded:
            raise RuntimeError("Mod is disabled")
        screen.mod_owner = self.id
        screen.mod_context = "mod." + self.id
        self._manager.app.push_screen(screen)

    def toggle_popup(self, screen):
        if getattr(self._manager.app.screen, "mod_owner", None) == self.id:
            self._manager.app.screen.dismiss()
        else:
            self.popup(screen)

    async def notify(self, text, **kwargs):
        if self.id not in self._manager.loaded:
            raise PermissionError(f"{self.id}: Mod is disabled")
        entry = self._manager.entries[self.id]
        policy = self._manager.policy(self.id)
        if (
            self.id not in self._manager.loaded
            or "notifications" not in entry["permissions"]
            or not policy.get("notifications", False)
        ):
            raise PermissionError(f"{self.id}: notification permission is not granted")
        return await self._manager.app.notification_events.publish(
            text, source="mod." + self.id, ui_mod=self.id, **kwargs
        )
