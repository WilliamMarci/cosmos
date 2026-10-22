"""Shared notification-event presenter, with service-synchronized action choices."""

from textual.message import Message

from cosmos_tui.ui.cell_surface import CellSurface
from cosmos_tui.ui.cells import (
    CellRun,
    HitRegion,
    Rect,
    UIFrame,
    UIRegistry,
    cell_width,
    clip,
)
from cosmos_tui.ui.zones import Zone


class NoticeToast(CellSurface):
    DEFAULT_CSS = (
        "NoticeToast { layer: notices; position: absolute; max-width: 60; height: 1; }"
    )

    class Action(Message):
        def __init__(self, notification, action):
            super().__init__()
            self.notification, self.action = notification, action

    def __init__(self, **kwargs):
        registry = UIRegistry()
        registry.attach("notification", Zone.NOTIFICATION, self.choose)
        super().__init__(registry, "notification", **kwargs)
        self.notification = None
        self.display = False

    def choose(self, action):
        if self.notification:
            self.post_message(self.Action(self.notification["id"], action))

    def present_notice(self, notice, width, height, palette):
        self.notification = notice
        self.display = bool(notice)
        if not notice:
            return
        actions = [(a["id"], a["label"]) for a in notice.get("actions", [])] + [
            ("__dismiss__", "×")
        ]
        max_width = min(width, 60)
        shown = actions if max_width >= 3 * len(actions) + 4 else actions[-1:]
        text = clip(notice["text"], max(0, max_width - 3 * len(shown) - 1))
        total = min(max_width, cell_width(text) + 1 + 3 * len(shown))
        x, y = width - total, max(0, height - 2)
        runs = [CellRun(Rect(x, y, total), text, palette["fg"], palette["base"])]
        hits = []
        for i, (action, label) in enumerate(shown):
            rect = Rect(x + total - 3 * len(shown) + i * 3, y, 3)
            label = clip(label, 3)
            left = max(0, (3 - cell_width(label)) // 2)
            runs.append(
                CellRun(rect, " " * left + label, palette["accl"], palette["base"])
            )
            hits.append(HitRegion(action, rect))
        self.present(UIFrame(Rect(x, y, total), tuple(runs), tuple(hits)))
