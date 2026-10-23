"""Status bar layout and click targets; no literal separators or terminal writes."""

from rich.text import Text
from rich.style import Style
from textual.widgets import Static


def short_path(path, depth, maximum):
    if maximum <= 0:
        return ""
    parts = path.split("/")
    if depth and len([p for p in parts if p]) > depth:
        path = "…/" + "/".join(parts[-depth:])
    if Text(path).cell_len > maximum:
        while path and Text("…" + path).cell_len > maximum:
            path = path[1:]
        path = "…" + path
    return path


def transition(style, before, after, direction="right"):
    """Join actual neighboring background colors, including gradient endpoints."""
    if style == "none":
        return Text()
    if style == "capsule":
        glyph = "" if direction == "left" else ""
    elif style == "powerline":
        glyph = "" if direction == "left" else ""
    else:
        glyph = "│" if style == "vertical" else "╲" if direction == "left" else "╱"
    foreground, background = (after, before) if direction == "left" else (before, after)
    return Text(glyph, style=Style(color=foreground, bgcolor=background))


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
        light = app.settings.get("theme", "dark") == "light"
        session_bg = "#d0d4dc" if light else "#292d38"
        path_bg = "#bfc5cf" if light else "#363c48"
        separator_style = app.settings.get("status_separator", "powerline")
        separator = "" if separator_style == "none" else " "
        alignment = app.settings.get("status_path_align", "right")

        def divide(before, after, direction="right"):
            return transition(separator_style, before, after, direction)

        start_end = start.get_style_at_offset(app.console, len(start) - 1).bgcolor
        start_begin = start.get_style_at_offset(app.console, 0).bgcolor
        if separator_style == "capsule":
            start = divide(palette["base"], start_begin, "left") + start
            self.start_width = min(width, start.cell_len)
            self.hits[0] = (0, self.start_width, "start")
        left = start + divide(start_end, session_bg)
        left += Text(f" {index}", style=Style(color="#e8a662", bgcolor=session_bg))
        left += Text(f" {name} ", style=Style(color=palette["fg"], bgcolor=session_bg))
        left += divide(session_bg, palette["base"])
        language = "中" if app.ime.enabled else "En"
        right = Text(style=base)
        path = short_path(
            path,
            app.settings.get("status_path_depth", 3),
            app.settings.get("status_path_max_length", 40),
        )
        if branch:
            path += f" ({branch})"
        # Reserve the clock and IME hit targets before allocating path space.
        budget = max(
            0,
            width
            - min(left.cell_len, self.start_width + 12)
            - len(clock)
            - 10
            - 2 * len(separator),
        )
        path = (
            short_path(
                path, 0, min(app.settings.get("status_path_max_length", 40), budget)
            )
            if budget
            else ""
        )
        path_text = Text(style=base)
        if path:
            direction = "left" if alignment in ("right", "center") else "right"
            before = palette["base"]
            if alignment == "left":
                if separator:
                    left = left[:-1]
                before = session_bg
            path_text = divide(before, path_bg, direction)
            path_text += Text(
                " " + path + " ", style=Style(color=palette["fg"], bgcolor=path_bg)
            )
            path_text += divide(
                path_bg,
                palette["bg"] if alignment == "right" else palette["base"],
                "right"
                if alignment == "center" or separator_style == "capsule"
                else direction,
            )
        if alignment == "left":
            left += path_text
        elif alignment == "right":
            right += path_text
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
        if right.cell_len > max(0, width - self.start_width):
            right = right[: max(0, width - self.start_width)]
        left.truncate(
            max(self.start_width, width - right.cell_len), overflow="ellipsis"
        )
        right_x = max(left.cell_len, width - right.cell_len)
        middle = Text(" " * max(0, right_x - left.cell_len), style=base)
        center_text = path_text.copy() if alignment == "center" else Text(style=base)
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
            (right_x + clock_offset, right_x + right.cell_len, "clock"),
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
        if action == "clock":
            return self.app.ui_mods.activate_status("clock")
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
