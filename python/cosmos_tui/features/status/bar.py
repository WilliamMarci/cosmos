"""Status bar layout and click targets; no literal separators or terminal writes."""

from rich.text import Text
from rich.style import Style
from textual.widgets import Static

SUPERSCRIPT = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


class StatusBar(Static):
    start_width = 8

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hits = []

    def present(
        self,
        *,
        label,
        index,
        name,
        path,
        branch,
        details="",
        center=(),
        clock="",
        mode="cosmos",
    ):
        app = self.app
        palette = app.role_colors
        colors = app.settings.get("status_colors", {})
        button = colors.get(
            mode,
            dict(
                cosmos="blue", image="green", doc="green", agent="magenta", files="red"
            )[mode],
        )
        foreground = colors.get("foreground", "bright_white")
        base = Style(color=palette["fg"], bgcolor=palette["base"], bold=False)
        width = self.size.width
        self.hits = []
        title = " " + label + " "
        if mode == "cosmos" and "cosmos" not in colors:
            start = Text()
            begin, end = (255, 209, 102), (22, 138, 112)
            dark_begin, dark_end = (58, 49, 32), (16, 48, 39)
            for i, character in enumerate(title):
                fraction = max(0, min(1, (i - 1) / max(1, len(label) - 1)))
                color = "#%02x%02x%02x" % tuple(
                    round(a + (b - a) * fraction) for a, b in zip(begin, end)
                )
                background = "#%02x%02x%02x" % tuple(
                    round(a + (b - a) * fraction) for a, b in zip(dark_begin, dark_end)
                )
                start.append(
                    character,
                    style=Style(
                        color=color,
                        bgcolor=background,
                        bold=True,
                    ),
                )

        else:
            start = Text(
                title, style=Style(color=foreground, bgcolor=button, bold=True)
            )
        self.start_width = min(width, start.cell_len)
        self.hits.append((0, self.start_width, "start"))
        left = start + Text(f" {str(index).translate(SUPERSCRIPT)} {name} ", style=base)
        language = "中" if app.ime.enabled else "En"
        right = Text(style=base)
        if details:
            right.append(" " + details + " ", style=palette["accl"])
        if path:
            right.append(" " + path + (f" ({branch})" if branch else "") + " ")
        language_offset = right.cell_len
        right.append(
            " " + language + " ",
            style=Style(color=palette["accl"], bgcolor=palette["bg"], bold=False),
        )
        width_offset = right.cell_len
        right.append(
            " " + ("●" if app.ime.full else "◐") + " ",
            style=Style(color=palette["accl"], bgcolor=palette["bg"], bold=False),
        )
        clock_offset = right.cell_len
        right.append(
            " " + clock + " ", style=Style(color=palette["fg"], bgcolor=palette["bg"])
        )
        # Drop long paths/details before reducing essential left and right controls.
        if left.cell_len + right.cell_len > width and (path or details):
            return self.present(
                label=label,
                index=index,
                name=name,
                path="",
                branch="",
                details=details if path else "",
                center=center,
                clock=clock,
                mode=mode,
            )
        if right.cell_len > max(0, width - self.start_width):
            right = right[: max(0, width - self.start_width)]
        left.truncate(
            max(self.start_width, width - right.cell_len), overflow="ellipsis"
        )
        right_x = max(left.cell_len, width - right.cell_len)
        middle = Text(" " * max(0, right_x - left.cell_len), style=base)
        center_text = Text(style=base)
        for text, role in center:
            center_text.append(
                " " + text + " ", style=palette.get(role, palette["mute"])
            )
        if center_text.cell_len and center_text.cell_len <= middle.cell_len:
            offset = width // 2 - center_text.cell_len // 2 - left.cell_len
            if 0 <= offset <= middle.cell_len - center_text.cell_len:
                middle = (
                    middle[:offset]
                    + center_text
                    + middle[offset + center_text.cell_len :]
                )
        self.hits += [
            (right_x + language_offset, right_x + width_offset, "language"),
            (right_x + width_offset, right_x + clock_offset, "width"),
        ]
        content = left + middle + right
        if content != getattr(self, "_content", None):
            self._content = content
            self.update(content)

    def activate_at(self, x):
        action = next(
            (action for left, right, action in self.hits if left <= x < right),
            None,
        )
        if action is None and x < self.start_width:
            action = "start"
        if action:
            if action == "start":
                self.app.action_start_menu()
            else:
                self.app.run_worker(
                    self.app.ime.toggle()
                    if action == "language"
                    else self.app.ime.toggle_width()
                )

        return action is not None

    def on_click(self, event):
        if self.activate_at(event.x):
            event.stop()
