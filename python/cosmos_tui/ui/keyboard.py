"""Compact keyboard preview adapted from design/cosmos_keys.py; semantic colors."""

from rich.text import Text
from textual.widgets import Static

LAYOUT = [
    [("Esc", 1), *[(c, 1) for c in "1234567890-="], ("Bksp", 2), ("Del", 1)],
    [("Tab", 1.5), *[(c, 1) for c in "QWERTYUIOP[]"], ("\\", 1.5), ("PgUp", 1)],
    [("Caps", 1.75), *[(c, 1) for c in "ASDFGHJKL;'"], ("Enter", 2.25), ("PgDn", 1)],
    [
        ("Shift", 2.25),
        *[(c, 1) for c in "ZXCVBNM,./"],
        ("Shift", 1.75),
        ("Up", 1),
        ("End", 1),
    ],
    [
        ("Ctrl", 1.25),
        ("Win", 1.25),
        ("Alt", 1.25),
        ("Space", 6.25),
        ("Alt", 1),
        ("Win", 1),
        ("Ctrl", 1),
        ("Left", 1),
        ("Down", 1),
        ("Right", 1),
    ],
]
NAMES = dict(
    ctrl="Ctrl",
    alt="Alt",
    shift="Shift",
    super="Win",
    escape="Esc",
    backspace="Bksp",
    delete="Del",
    pageup="PgUp",
    pagedown="PgDn",
    left_square_bracket="[",
    right_square_bracket="]",
    quotation_mark='"',
    percent_sign="%",
    vertical_line="|",
    question_mark="?",
    full_stop=".",
    comma=",",
    slash="/",
    minus="-",
    equals_sign="=",
)
SHIFTED = dict(zip('!@#$%^&*()_+{}|:"<>?', "1234567890-=[]\\;',./"))


def physical_keys(bindings, leader="C-b"):
    keys = set()
    for binding in bindings:
        for part in binding.replace("Leader ", "leader+").split("+"):
            if part.lower() == "leader":
                keys.update(("Ctrl", leader[-1].upper()))
                continue
            value = NAMES.get(part.lower(), part.title() if len(part) > 1 else part)
            if value in SHIFTED:
                keys.update(("Shift", SHIFTED[value].upper()))
            else:
                if len(value) == 1 and value.isupper():
                    keys.add("Shift")
                keys.add(value.upper() if len(value) == 1 else value)
    return keys


class KeyboardPreview(Static):
    DEFAULT_CSS = "KeyboardPreview { width: 64; height: 10; margin: 0; padding: 0; }"

    def __init__(self, keys=(), **kwargs):
        super().__init__("", markup=False, **kwargs)
        self.keys = keys

    def present(self, keys):
        self.keys = keys
        self.update(self.drawing())

    def on_mount(self):
        self.update(self.drawing())

    def drawing(self):
        palette = self.app.role_colors
        first, second = key_phases(
            self.keys, getattr(self.app, "settings", {}).get("leader", "C-b")
        )
        text = Text()
        glyphs = dict(
            Left="←", Right="→", Up="↑", Down="↓", PgUp="PgU", PgDn="PgD", Space=""
        )
        for row in LAYOUT:
            offset = 0
            for name, units in row:
                end = round(offset + units * 4)
                width = end - round(offset) - 1
                label = glyphs.get(name, name)[:width].center(width)
                selected = name in first or name in second
                background = (
                    "#FFD166"
                    if name in first
                    else "#168A70"
                    if name in second
                    else palette["base"]
                )
                text.append(
                    label,
                    style=f"{palette['on'] if selected else palette['fg']} on {background}",
                )
                text.append("▌", style=palette["bg"])
                offset += units * 4
            text.append("\n" + "▀" * 64 + "\n", style=palette["bg"])
        return text

    def fit(self, *, minimum_height=24):
        self.display = (
            self.app.size.width >= 74 and self.app.size.height >= minimum_height
        )


def key_phases(bindings, leader="C-b"):
    first, second = set(), set()
    for binding in bindings:
        value = binding.strip().replace("Leader ", "leader+")
        if value.startswith("leader+"):
            first.update(physical_keys(["ctrl+" + leader[-1]]))
            second.update(physical_keys([value[len("leader+") :]]))
        else:
            strokes = value.split()
            if strokes:
                first.update(physical_keys([strokes[0]]))
                second.update(physical_keys(strokes[1:]))
    return first, second


def key_legend(palette):
    text = Text()
    text.append(" First press ", style=f"{palette['on']} on #FFD166")
    text.append("  ")
    text.append(" Next press ", style="white on #168A70")
    return text
