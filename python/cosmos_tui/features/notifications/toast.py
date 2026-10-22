"""Compact right-aligned notification stack: one row, at most two per notice."""

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

COLORS = dict(
    error="#e06c75",
    warning="#e8a662",
    info="#62a0e6",
    success="#8dbf7a",
    progress="#56b6c2",
)


class NoticeToast(CellSurface):
    DEFAULT_CSS = "NoticeToast { layer: notices; position: absolute; max-width: 60; }"

    class Action(Message):
        def __init__(self, notification, action):
            super().__init__()
            self.notification, self.action = notification, action

    def __init__(self, **kwargs):
        registry = UIRegistry()
        registry.attach("notification", Zone.NOTIFICATION, self.choose)
        super().__init__(registry, "notification", **kwargs)
        self.notices = {}
        self.notification = None
        self.display = False

    def choose(self, action):
        notification, _, selected = action.partition(":")
        if notification.isdigit() and int(notification) in self.notices:
            self.post_message(self.Action(int(notification), selected))

    def present_notice(self, notice, width, height, palette):
        self.present_notices([notice] if notice else [], width, height, palette)

    def present_notices(
        self, notices, width, height, palette, *, status_rows=1, pane_width=None
    ):
        self.notices = {notice["id"]: notice for notice in notices}
        self.notification = notices[-1] if notices else None
        self.display = bool(notices) and width > 1 and height > status_rows
        if not self.display:
            return
        available = max(2, int(min(width, 60, pane_width or width) * 0.7))
        limit = height - status_rows
        top = 0
        runs, hits = [], []
        left = width
        for notice in reversed(notices):
            actions = [(a["id"], a["label"]) for a in notice.get("actions", [])] + [
                ("__dismiss__", "×")
            ]
            actions = actions if available >= 3 * len(actions) + 4 else actions[-1:]
            if available < 5:
                actions = actions[-1:]
            button_width = 3 * len(actions) if available >= 5 else 1
            text_width = max(0, available - button_width - 2)
            session = str(notice.get("session_id") or "").removeprefix("$")
            tag = (
                session.translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))
                if session.isdigit()
                else ""
            )
            text = (tag + " " if tag else "") + notice["text"]
            count = notice.get("count", 1)
            suffix = clip(f" ×{count}", text_width) if count > 1 else ""
            suffix_width = cell_width(suffix)
            first = clip(text, text_width)
            remaining = text[len(first) :] if text_width else ""
            second = clip(remaining, text_width)
            if len(second) < len(remaining) and text_width > 1:
                second = clip(second, text_width - 1) + "…"
            rows = (
                2 if remaining or cell_width(first) + suffix_width > text_width else 1
            )
            if rows == 2 and not remaining:
                first = clip(text, max(0, text_width - suffix_width))
                remaining = text[len(first) :]
                second = remaining
            if rows > limit - top:
                if limit - top < 1:
                    break
                rows, second = 1, ""
                first = clip(first, max(0, text_width - 1)) + "…"
            if suffix:
                if rows == 1:
                    first = clip(first, max(0, text_width - suffix_width))
                else:
                    capacity = max(0, text_width - suffix_width)
                    second = clip(remaining, capacity)
                    if len(second) < len(remaining) and capacity:
                        second = clip(second, capacity - 1) + "…"
            content_width = max(cell_width(first), cell_width(second))
            total = available
            x, y = width - total, top
            left = min(left, x)
            level = COLORS.get(notice.get("level", "info"), COLORS["info"])
            for row, value in enumerate((first, second)[:rows]):
                runs.append(
                    CellRun(Rect(x, y + row, total), "", palette["fg"], palette["base"])
                )
                runs.append(CellRun(Rect(x, y + row, 1), "▐", level, palette["base"]))
                if content_width:
                    runs.append(
                        CellRun(
                            Rect(x + 2, y + row, content_width),
                            value,
                            palette["fg"],
                            palette["base"],
                        )
                    )
            if suffix:
                last_text = first if rows == 1 else second
                runs.append(
                    CellRun(
                        Rect(x + 2 + cell_width(last_text), y + rows - 1, suffix_width),
                        suffix,
                        COLORS["warning"],
                        palette["base"],
                    )
                )
            for index, (action, label) in enumerate(actions):
                rect = Rect(
                    x + total - button_width + index * 3,
                    y + rows - 1,
                    min(3, button_width - index * 3),
                )
                if rect.width <= 0:
                    continue
                label = clip(label, rect.width)
                label = " " * max(0, (rect.width - cell_width(label)) // 2) + label
                runs.append(CellRun(rect, label, palette["accl"], palette["base"]))
                hits.append(HitRegion(f"{notice['id']}:{action}", rect))
            top += rows
            if top >= limit:
                break
        self.present(
            UIFrame(
                Rect(left, 0, width - left, top),
                tuple(runs),
                tuple(hits),
            )
        )
