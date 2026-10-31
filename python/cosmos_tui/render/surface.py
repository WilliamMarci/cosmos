from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip
from textual.widget import Widget

from cosmos_tui.features.history.selection import selection_range
from cosmos_tui.features.theme.palettes import terminal_palette, terminal_style
from cosmos_tui.render.borders import borders
from cosmos_tui.ui.cells import cell_width
from cosmos_tui.ui.chrome import frame_border
from cosmos_tui.ui.zones import Zone


class TerminalSurface(Widget):
    zone = Zone.SESSION_WINDOW
    can_focus = True

    def render_line(self, y):
        width = self.size.width
        palette = self.app.role_colors
        terminal = terminal_palette(self.app.settings.get("terminal_theme", "inherit"))
        style = Style(color=terminal["fg"], bgcolor=terminal["bg"])
        border_row = borders(
            width,
            self.size.height,
            tuple((p.x, p.y, p.width, p.height, p.active) for p in self.app.panes),
        ).get(y, {})

        def gutter(left, right):
            segments = []
            for column in range(left, right):
                glyph, active = border_row.get(column, (" ", False))
                segments.append(
                    Segment(
                        glyph,
                        Style(
                            color=palette["acc"] if active else palette["mute"],
                            bgcolor=palette["bg"],
                        ),
                    )
                )
            return Strip(segments)

        parts = []
        x = 0
        for pane in sorted(self.app.panes, key=lambda p: p.x):
            if not pane.y <= y < pane.y + pane.height:
                continue
            if pane.x > x:
                parts.append(gutter(x, pane.x))
            lines = self.app.lines.get(pane.id, [])
            row = y - pane.y
            text = lines[row] if row < len(lines) else Text("", style=style)
            text = text.copy()
            text.stylize_before(style)
            pane_terminal = (
                terminal
                if not pane.viewer
                else dict(fg=palette["fg"], bg=palette["bg"], ansi=None)
            )
            strip = (
                Strip(
                    Segment(
                        segment.text,
                        terminal_style(segment.style, pane_terminal),
                        segment.control,
                    )
                    for segment in text.render(self.app.console, end="")
                )
                .crop(0, pane.width)
                .extend_cell_length(pane.width, style)
            )
            selected = selection_range(pane, row)
            if (
                not selected
                and pane.copy_mode
                and pane.copy_match
                and row == pane.cursor[1]
            ):
                selected = (
                    pane.cursor[0],
                    min(pane.width, pane.cursor[0] + cell_width(pane.copy_match)),
                )
            if selected:
                left, right = selected
                strip = Strip.join(
                    [
                        strip.crop(0, left),
                        strip.crop(left, right).apply_style(
                            Style(color=palette["on"], bgcolor=palette["acc"])
                        ),
                        strip.crop(right, pane.width),
                    ]
                )
            if (
                getattr(getattr(self.app, "workspace", None), "identifying", False)
                and row == pane.height // 2
            ):
                label = f" {pane.index} · {pane.id} "
                label = label[: pane.width]
                left = max(0, (pane.width - len(label)) // 2)
                badge = Strip(
                    [
                        Segment(
                            label,
                            Style(
                                color=palette["on"], bgcolor=palette["acc"], bold=True
                            ),
                        )
                    ]
                )
                strip = Strip.join(
                    [
                        strip.crop(0, left),
                        badge,
                        strip.crop(left + len(label), pane.width),
                    ]
                )
            parts.append(strip)
            x = pane.x + pane.width
        if x < width:
            parts.append(gutter(x, width))
        strip = Strip.join(parts).crop(0, width)
        for layer in self.app.views:
            view = layer["view"]
            rect = layer["rect"]
            if not rect["y"] <= y < rect["y"] + rect["height"]:
                continue
            row = y - rect["y"]
            content = view["content"]
            framed = (
                view["kind"] in ("palette", "help")
                and rect["width"] >= 4
                and rect["height"] >= 3
            )
            if framed and row in (0, rect["height"] - 1):
                rendered = frame_border(
                    rect["width"],
                    palette,
                    Text(content.get("title", ""), style=palette["fg"]),
                    top=row == 0,
                )
            else:
                items = (
                    content.get("lines", [])
                    if framed
                    else [
                        {"text": content.get("title", ""), "role": "acc"},
                        *content.get("lines", []),
                    ]
                )
                index = row - 1 if framed else row
                item = (
                    items[index] if index < len(items) else {"text": "", "role": "fg"}
                )
                rendered = Text(
                    item["text"],
                    style=Style(
                        color=palette.get(item["role"], palette["fg"]),
                        bgcolor=palette["base"],
                    ),
                )
                if framed:
                    rendered.truncate(rect["width"] - 2)
                    rendered.pad_right(rect["width"] - 2 - cell_width(rendered.plain))
                    edge = Text(
                        "│", style=Style(color=palette["acc"], bgcolor=palette["base"])
                    )
                    rendered = edge + rendered + edge
            overlay = (
                Strip(
                    Segment(s.text, s.style or style, s.control)
                    for s in rendered.render(self.app.console, end="")
                )
                .crop(0, rect["width"])
                .extend_cell_length(rect["width"], Style(bgcolor=palette["base"]))
            )
            strip = Strip.join(
                [
                    strip.crop(0, rect["x"]),
                    overlay,
                    strip.crop(rect["x"] + rect["width"], width),
                ]
            ).crop(0, width)
        from cosmos_tui.features.agent.header_ui import paint_headers

        return paint_headers(self.app, strip, y, width)
