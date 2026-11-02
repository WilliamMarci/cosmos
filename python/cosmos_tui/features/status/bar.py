"""Status bar layout and click targets; no literal separators or terminal writes."""

from rich.text import Text
from rich.style import Style
from textual.widgets import Static
from cosmos_tui.ui.blocks import gradient_block, transition


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
        file_info=None,
        identity=None,
        history="",
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
            logo = app.theme_logo
            start = gradient_block(label, logo.foreground, logo.background)
        else:
            start = Text(
                title, style=Style(color=foreground, bgcolor=button, bold=True)
            )
        self.start_width = min(width, start.cell_len)
        self.hits.append((0, self.start_width, "start"))
        light = bool(getattr(app, "theme_is_light", False))
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
        identity_start = left.cell_len
        if identity is not None and "·" in identity:
            session, _, position = identity.rpartition("·")
            left += Text(" " + session, style=Style(color=palette["fg"], bgcolor=session_bg))
            left += Text("·", style=Style(color=palette["mute"], bgcolor=session_bg))
            window, separator, pane = position.partition(":")
            if separator:
                left += Text(window, style=Style(color="#e8a662", bgcolor=session_bg))
                left += Text(":", style=Style(color=palette["mute"], bgcolor=session_bg))
            else:
                pane = window
            left += Text(pane, style=Style(color=palette["accl"], bgcolor=session_bg))
        else:
            left += Text(f" {index}", style=Style(color="#e8a662", bgcolor=session_bg))
        identity_end = left.cell_len
        left += Text(f" {name} ", style=Style(color=palette["fg"], bgcolor=session_bg))
        if getattr(app.inputs, "keyboard_passthrough", False):
            left += Text(
                "KEYS OFF ",
                style=Style(color=palette["accl"], bgcolor=session_bg, bold=True),
            )
        left += divide(session_bg, palette["base"])
        if file_info:
            from cosmos_tui.features.files.model import display

            left += Text(
                " " + file_info.get("size", "") + " ",
                style=Style(color=palette["accl"], bgcolor=session_bg),
            )
            left += Text(display(file_info.get("name", "")) + " ", style=base)
        language = "中" if app.ime.enabled else "En"
        right = Text(style=base)
        path = short_path(
            path,
            app.settings.get("status_path_depth", 3),
            app.settings.get("status_path_max_length", 40),
        )
        # Reserve the clock and IME hit targets before allocating path space.
        budget = max(
            0,
            width
            - min(left.cell_len, self.start_width + 12)
            - len(clock)
            - 10
            - 2 * len(separator)
            - (len(history) + 2 if history else 0),
        )
        branch_text = Text(branch or "")
        branch_text.truncate(min(24, max(0, budget // 2)), overflow="ellipsis")
        branch = branch_text.plain
        branch_space = branch_text.cell_len + 3 if branch else 0
        path_budget = max(0, budget - branch_space)
        path = (
            short_path(
                path,
                0,
                min(app.settings.get("status_path_max_length", 40), path_budget),
            )
            if path_budget
            else ""
        )
        path_text = Text(style=base)
        if path or branch:
            direction = "left" if alignment in ("right", "center") else "right"
            before = palette["base"]
            if alignment == "left":
                if separator:
                    left = left[:-1]
                before = session_bg
            after = before
            if path:
                path_text = divide(before, path_bg, direction)
                path_text += Text(
                    " " + path + " ", style=Style(color=palette["fg"], bgcolor=path_bg)
                )
                after = path_bg
            if branch:
                branch_bg = "#d0d4dc" if light else "#292d38"
                path_text += divide(after, branch_bg, direction)
                path_text += Text(
                    " " + branch + " ",
                    style=Style(color=palette["accl"], bgcolor=branch_bg),
                )
                after = branch_bg
            path_text += divide(
                after,
                palette["bg"] if alignment == "right" else palette["base"],
                "right"
                if alignment == "center" or separator_style == "capsule"
                else direction,
            )
        if alignment == "left":
            left += path_text
        elif alignment == "right":
            right += path_text
        if file_info:
            from cosmos_tui.features.files.style import permission_text

            if width >= 90:
                right += permission_text(file_info.get("permissions", ""), palette)
                right.append(" " + file_info.get("owner", "") + " ", style=base)
            if width >= 65:
                right.append(
                    " " + file_info.get("percent", "") + " ", style=palette["accl"]
                )
            right.append(
                " " + file_info.get("position", "") + " ",
                style=Style(color=palette["on"], bgcolor=palette["acc"]),
            )
        if history:
            right.append(
                " " + history + " ",
                style=Style(color=palette["accl"], bgcolor=palette["base"]),
            )
        language_offset = right.cell_len
        right.append(
            " " + language + " ",
            style=Style(color=palette["accl"], bgcolor=palette["bg"], bold=False),
        )
        width_offset = right.cell_len
        right.append(
            " " + ("▧" if app.ime.full else "◐") + " ",
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
        if identity is not None and identity_start < min(identity_end, left.cell_len):
            self.hits.append((identity_start, min(identity_end, left.cell_len), "switch"))
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
            if action == "switch":
                from cosmos_tui.features.navigation.switcher import Switcher

                self.app.push_screen(Switcher())
            elif action == "start":
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
