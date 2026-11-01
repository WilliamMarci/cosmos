#!/usr/bin/env python3
"""Compact shaded keyboard for previewing / editing Cosmos shortcuts."""
import argparse
import curses
import json
import locale
import os
import sys
from pathlib import Path

# (name, width in units). Every row totals 16u; 1u = 4 columns
# (3 columns of key body + 1 column holding the right-hand shadow).
def _row(*items):
    return list(items)

LAYOUT = [
    _row(("Esc", 1), *[(c, 1) for c in "1234567890-="],
         ("Bksp", 2), ("Del", 1)),
    _row(("Tab", 1.5), *[(c, 1) for c in "QWERTYUIOP[]"],
         ("\\", 1.5), ("PgUp", 1)),
    _row(("Caps", 1.75), *[(c, 1) for c in "ASDFGHJKL;'"],
         ("Enter", 2.25), ("PgDn", 1)),
    _row(("Shift", 2.25), *[(c, 1) for c in "ZXCVBNM,./"],
         ("Shift", 1.75), ("Up", 1), ("End", 1)),
    _row(("Ctrl", 1.25), ("Win", 1.25), ("Alt", 1.25), ("Space", 6.25),
         ("Alt", 1), ("Win", 1), ("Ctrl", 1),
         ("Left", 1), ("Down", 1), ("Right", 1)),
]

MODIFIERS = {"Ctrl": "Ctrl", "Alt": "Alt", "Shift": "Shift", "Win": "Super"}
MOD_ORDER = ["Ctrl", "Alt", "Shift", "Super"]
MOD_KEYS = {"1": "Ctrl", "2": "Alt", "3": "Shift", "4": "Super"}

GLYPHS = {"Left": "←", "Down": "↓", "Up": "↑", "Right": "→",
          "PgUp": "PgU", "PgDn": "PgD", "Space": ""}
ASCII_GLYPHS = {"Left": "<", "Down": "v", "Up": "^", "Right": ">",
                "PgUp": "PgU", "PgDn": "PgD", "Space": ""}

DEFAULT_BINDINGS = {
    "Ctrl+K": "palette", "Ctrl+N": "new-session", "Ctrl+W": "close",
    "Ctrl+P": "projects", "Alt+H": "focus-left", "Alt+J": "focus-down",
    "Alt+K": "focus-up", "Alt+L": "focus-right", "Alt+1": "workspace-1",
    "Alt+2": "workspace-2", "Alt+3": "workspace-3", "Super+D": "dashboard",
    "Ctrl+Shift+P": "agent",
    "Alt+Left": "focus-left", "Alt+Right": "focus-right",
    "Alt+Up": "focus-up", "Alt+Down": "focus-down",
}

# state: (cap bg 256, fg 256, cap bg 8-color, fg 8-color)
STYLES = {
    "normal": (239, 252, 0, 7),    # unbound key
    "mod":    (240, 147, 0, 4),    # modifier key
    "bound":  (111, 16, 4, 0),     # has an action in this layer
    "active": (189, 16, 6, 0),     # modifier layer switched on
    "cursor": (255, 16, 7, 0),     # current selection
}
STATE_ORDER = list(STYLES)
SHADOW_256, SHADOW_8 = 234, 0

ROW_PITCH = 2          # key line + shadow line, no blank row
TOP = 2
KB_WIDTH = 64
KB_HEIGHT = TOP + len(LAYOUT) * ROW_PITCH

def build(ascii_mode=False):
    glyphs = ASCII_GLYPHS if ascii_mode else GLYPHS
    keys = []
    for r, row in enumerate(LAYOUT):
        cum = 0.0
        for name, units in row:
            x0 = round(cum * 4)
            x1 = round((cum + units) * 4)
            cum += units
            w = x1 - x0 - 1           # body width; +1 column of shadow
            label = glyphs.get(name, name)[:w]
            keys.append({"name": name, "row": r, "x": x0, "w": w,
                         "y": TOP + r * ROW_PITCH,
                         "label": label.center(w)})
    return keys

def combo(mods, name):
    return "+".join([m for m in MOD_ORDER if m in mods] + [name])

def key_state(k, bindings, mods, cur):
    if k is cur:
        return "cursor"
    if k["name"] in MODIFIERS:
        return "active" if MODIFIERS[k["name"]] in mods else "mod"
    return "bound" if combo(mods, k["name"]) in bindings else "normal"

def chips(mods):
    return [(f" {m} ", "active" if m in mods else "mod")
            for m in MOD_ORDER]

# ---------- plain ANSI output ----------
def ansi_key(k, state, color):
    if not color:
        text = k["label"].strip().center(k["w"] - 2)
        pair = "()" if state == "bound" else "[]"
        return pair[0] + text + pair[1] + " "
    bg, fg = STYLES[state][:2]
    body = f"\x1b[48;5;{bg};38;5;{fg}m{k['label']}"
    edge = f"\x1b[38;5;{bg};48;5;{SHADOW_256}m▌"
    return body + edge + "\x1b[0m"

def render_print(bindings, mods, color=True, ascii_mode=False):
    keys = build(ascii_mode)
    shadow = (f"\x1b[38;5;{SHADOW_256}m" + "▀" * KB_WIDTH + "\x1b[0m"
              if color else "")
    head = ""
    for text, state in chips(mods):
        if color:
            bg, fg = STYLES[state][:2]
            head += f"\x1b[48;5;{bg};38;5;{fg}m{text}\x1b[0m "
        else:
            head += ("[" + text.strip() + "]" if state == "active"
                     else " " + text.strip() + " ") + " "
    lines = [head.rstrip(), ""]
    for r in range(len(LAYOUT)):
        lines.append("".join(
            ansi_key(k, key_state(k, bindings, mods, None), color)
            for k in keys if k["row"] == r))
        if color:
            lines.append(shadow)
    return "\n".join(lines)

# ---------- config ----------
def load(path):
    p = Path(path)
    if not p.exists():
        return dict(DEFAULT_BINDINGS)
    data = json.loads(p.read_text(encoding="utf-8"))
    return dict(data.get("bindings", {}))

def save(path, bindings):
    data = {"format": "cosmos-keys-v1",
            "bindings": dict(sorted(bindings.items()))}
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

def neighbor(keys, cur, direction):
    cx = cur["x"] + cur["w"] / 2
    best, best_score = None, None
    for k in keys:
        if k is cur:
            continue
        dx = k["x"] + k["w"] / 2 - cx
        dy = k["row"] - cur["row"]
        if direction == "left" and dy == 0 and dx < 0:
            score = -dx
        elif direction == "right" and dy == 0 and dx > 0:
            score = dx
        elif direction == "up" and dy < 0:
            score = -dy * 100 + abs(dx)
        elif direction == "down" and dy > 0:
            score = dy * 100 + abs(dx)
        else:
            continue
        if best_score is None or score < best_score:
            best, best_score = k, score
    return best or cur

# ---------- curses UI ----------
def init_colors():
    curses.start_color()
    curses.use_default_colors()
    rich = curses.COLORS >= 256
    shadow = SHADOW_256 if rich else SHADOW_8
    for i, state in enumerate(STATE_ORDER):
        bg256, fg256, bg8, fg8 = STYLES[state]
        bg, fg = (bg256, fg256) if rich else (bg8, fg8)
        curses.init_pair(10 + i, bg, shadow)   # right edge: cap | shadow
        curses.init_pair(30 + i, fg, bg)       # key body
    curses.init_pair(4, shadow, -1)                                # base line
    curses.init_pair(1, 147 if rich else curses.COLOR_CYAN, -1)    # accent
    curses.init_pair(2, 245 if rich else curses.COLOR_WHITE, -1)   # dim text
    curses.init_pair(3, 252 if rich else curses.COLOR_WHITE, -1)   # text

def put(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass

def draw_key(win, k, state):
    i = STATE_ORDER.index(state)
    body = curses.color_pair(30 + i) | (
        curses.A_BOLD if state == "cursor" else 0)
    put(win, k["y"], k["x"], k["label"], body)
    put(win, k["y"], k["x"] + k["w"], "▌", curses.color_pair(10 + i))

def ui(stdscr, path, ascii_mode):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    init_colors()
    keys = build(ascii_mode)
    bindings = load(path)
    mods = set()
    cur = next(k for k in keys if k["name"] == "Q")
    dirty, message = False, ""
    info_y = KB_HEIGHT + 1
    need_h, need_w = info_y + 5, KB_WIDTH

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < need_h or w < need_w:
            put(stdscr, 0, 0, f"终端至少需要 {need_w}x{need_h}，当前 {w}x{h}")
            stdscr.refresh()
            if stdscr.getch() in (ord("q"), 27):
                return
            continue

        x = 0
        for text, state in chips(mods):
            put(stdscr, 0, x, text,
                curses.color_pair(30 + STATE_ORDER.index(state)))
            x += len(text) + 1
        for r in range(len(LAYOUT)):
            put(stdscr, TOP + r * ROW_PITCH + 1, 0, "▀" * KB_WIDTH,
                curses.color_pair(4))
        for k in keys:
            draw_key(stdscr, k, key_state(k, bindings, mods, cur))

        layer = "+".join(m for m in MOD_ORDER if m in mods) or "基础层"
        count = sum(1 for b in bindings
                    if set(b.split("+")[:-1]) == mods)
        if cur["name"] in MODIFIERS:
            info = f"{cur['name']}  Enter 切换这一层"
        else:
            c = combo(mods, cur["name"])
            info = f"{c}  →  {bindings.get(c, '（未绑定）')}"
        put(stdscr, info_y, 0, info, curses.color_pair(3) | curses.A_BOLD)
        put(stdscr, info_y + 1, 0, f"{layer} · 本层 {count} 个绑定"
            + ("  ● 未保存" if dirty else ""), curses.color_pair(1))
        put(stdscr, info_y + 2, 0, message, curses.color_pair(1))
        put(stdscr, info_y + 4, 0,
            "←↑↓→/hjkl 移动  1-4 修饰键  Enter 编辑  d 删除  w 保存  q 退出",
            curses.color_pair(2))
        stdscr.refresh()

        ch = stdscr.getch()
        message = ""
        if ch in (curses.KEY_LEFT, ord("h")):
            cur = neighbor(keys, cur, "left")
        elif ch in (curses.KEY_RIGHT, ord("l")):
            cur = neighbor(keys, cur, "right")
        elif ch in (curses.KEY_UP, ord("k")):
            cur = neighbor(keys, cur, "up")
        elif ch in (curses.KEY_DOWN, ord("j")):
            cur = neighbor(keys, cur, "down")
        elif 0 <= ch < 256 and chr(ch) in MOD_KEYS:
            mods.symmetric_difference_update({MOD_KEYS[chr(ch)]})
        elif ch in (10, 13, curses.KEY_ENTER, ord("e")):
            if cur["name"] in MODIFIERS:
                mods.symmetric_difference_update({MODIFIERS[cur["name"]]})
            else:
                c = combo(mods, cur["name"])
                y = info_y + 2
                put(stdscr, y, 0, "action> ", curses.color_pair(1))
                try:
                    curses.curs_set(1)
                except curses.error:
                    pass
                curses.echo()
                raw = stdscr.getstr(y, 8, 40)
                curses.noecho()
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
                action = raw.decode("utf-8", "ignore").strip()
                if action:
                    bindings[c] = action
                    dirty = True
                    message = f"已设置 {c} → {action}"
                else:
                    message = "未修改（输入为空；删除请按 d）"
        elif ch in (ord("d"), curses.KEY_DC):
            c = combo(mods, cur["name"])
            if bindings.pop(c, None) is not None:
                dirty = True
                message = f"已删除 {c}"
        elif ch == ord("w"):
            save(path, bindings)
            dirty = False
            message = f"已保存到 {path}"
        elif ch in (ord("q"), 27):
            if dirty:
                message = "有未保存修改：按 w 保存，或按 Q 强制退出"
            else:
                return
        elif ch == ord("Q"):
            return

def main():
    locale.setlocale(locale.LC_ALL, "")
    parser = argparse.ArgumentParser(description="Cosmos 终端键盘")
    parser.add_argument("--config", default="cosmos_keys.json")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="只打印，不进入交互界面")
    parser.add_argument("--mods", default="",
                        help="预览的修饰键层，例如 Ctrl 或 Ctrl,Shift")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--ascii", action="store_true",
                        help="方向键改用 < v ^ >，字体缺少箭头时使用")
    args = parser.parse_args()

    mods = {m.strip().capitalize() for m in args.mods.split(",") if m.strip()}
    bad = mods - set(MOD_ORDER)
    if bad:
        parser.error(f"未知修饰键：{', '.join(sorted(bad))}；"
                     f"可用 {', '.join(MOD_ORDER)}")

    if args.print_only:
        color = not args.no_color and "NO_COLOR" not in os.environ
        out = render_print(load(args.config), mods, color, args.ascii)
        sys.stdout.buffer.write((out + "\n").encode("utf-8"))
    else:
        curses.wrapper(ui, args.config, args.ascii)

if __name__ == "__main__":
    main()
