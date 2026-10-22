import sys, os, tty, termios, unicodedata, shutil, math, random

def cw(c):
    if unicodedata.combining(c): return 0
    return 2 if unicodedata.east_asian_width(c) in 'WF' else 1
def w(s): return sum(cw(c) for c in s)
def clip(s, n):
    o, t = '', 0
    for c in s:
        if t + cw(c) > n: break
        o += c; t += cw(c)
    return o

# ---------- 调色板 ----------
BG0=(20,22,30); BG1=(32,35,46); BG2=(48,53,70)
ACC=(98,160,230); ACL=(160,205,250); GRN=(120,196,140); ORG=(232,166,98)
FG=(205,210,220); DIM=(120,126,142); DK=(16,18,26); WH=(232,235,242)
B='\x1b[1m'; U='\x1b[4m'; I='\x1b[3m'; R='\x1b[0m'
def sty(f=None, b=None, ex=''):
    s = R + ex
    if f: s += '\x1b[38;2;%d;%d;%dm' % f
    if b: s += '\x1b[48;2;%d;%d;%dm' % b
    return s
def at(r, c): return f'\x1b[{r};{c}H'
def segs_str(segs, width=None, padsty=None):
    o, used = '', 0
    for st, tx in segs:
        if width is not None: tx = clip(tx, width - used)
        o += st + tx; used += w(tx)
    if width is not None and used < width: o += (padsty or '') + ' ' * (width - used)
    return o + R, used
def swidth(segs): return sum(w(t) for _, t in segs)
def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

W_, H_ = shutil.get_terminal_size()
PROWS = H_ - 1

# ---------- 数据 ----------
DICT = {
 'nihao':[('你好','hello'),('拟好','draft well'),('泥壕','mud trench'),('尼好','-'),('你号','your number')],
 'zhongwen':[('中文','Chinese language'),('中温','medium temperature'),('钟文','a given name'),('种文','-')],
 'shijie':[('世界','world'),('视界','field of view'),('十届','tenth session'),('适解','-')],
 'fanyi':[('翻译','to translate'),('翻译官','interpreter'),('凡一','-')],
 'ceshi':[('测试','test'),('侧室','side room'),('策士','strategist')],
 'zhongduan':[('终端','terminal'),('中断','interrupt'),('钟段','-')],
}
WINS = [('shell',1,False),('vim',2,False),('agent',1,True),('logs',3,False),('docs',2,False)]
lines = ["def main():", "    config = load_config()", "    session = Session(config)",
         "    # 在这里输入拼音试试 ->", "    note = ''", "    for pane in session.panes:",
         "        pane.render()", "    return 0", "",
         "# 先按 ^A 再按: w 窗口切换  i 图片  p PDF"] + \
        [f"line_{i:02d} = {i} * 2  # 填充行" for i in range(11, 80)]

# ---------- 基础画面 ----------
def draw_pane():
    o = []
    for i in range(PROWS):
        t = lines[i] if i < len(lines) else ''
        if i < len(lines): o.append(at(i+1,1) + sty(FG) + t + ' ' * (W_ - w(t)) + R)
        else: o.append(at(i+1,1) + sty(BG2) + '~' + ' ' * (W_-1) + R)
    return ''.join(o)

def status(mode, cur, leader, composing, page, total):
    L = [(sty(DK, ACC, B), ' cosmos '), (sty(None, BG0), ' ')]
    for i, (n, _, pend) in enumerate(WINS):
        if i == cur: L.append((sty(DK, WH, B), f' {i+1} {n} '))
        else:        L.append((sty(DIM, BG2), f' {i+1} {n} '))
        if pend and i != cur: L.append((sty(None, ORG), ' '))
        L.append((sty(None, BG0), ' '))
    Rr = []
    if leader:
        Rr += [(sty(DK, ORG, B), ' ^A '), (sty(DIM, BG1), ' w 窗口  i 图片  p PDF ')]
    if mode == 'pdf': Rr += [(sty(FG, BG2, B), f' {page} / {total} ')]
    if composing:     Rr += [(sty(DK, ORG, B), ' 中 组字 ')]
    else:             Rr += [(sty(DIM, BG1), ' 中 ')]
    _, lw = segs_str(L); _, rw = segs_str(Rr)
    mid = max(0, W_ - lw - rw)
    return at(H_,1) + segs_str(L)[0] + sty(None, BG0) + ' ' * mid + segs_str(Rr)[0]

# ---------- 候选区(色块) ----------
def cand_overlay(r, c, pre, cands, hi):
    page = cands[:5]; gloss = page[hi][1]
    r1 = [(sty(ORG, BG2, U), ' ' + pre), (sty(ACC, BG2), '▏ ')]
    r2 = []
    for i, (t, _) in enumerate(page):
        if i == hi: r2 += [(sty(DK, ACC, B), f' {i+1}'), (sty(DK, ACL, B), f' {t} ')]
        else:       r2 += [(sty(DIM, BG2), f' {i+1}'), (sty(FG, BG1), f' {t} ')]
        r2.append((sty(None, BG0), ' '))
    if gloss != '-': r2.append((sty(GRN, (26,48,38), I), f' {gloss} '))
    BW = min(max(swidth(r1), swidth(r2), 24), W_)
    col = c if c + BW - 1 <= W_ else max(1, W_ - BW + 1)     # 右侧不足 -> 左移
    top = r + 1 if r + 2 <= PROWS else max(1, r - 2)         # 下方不足 -> 上方
    return (at(top, col) + segs_str(r1, BW, sty(None, BG2))[0] +
            at(top+1, col) + segs_str(r2, BW, sty(None, BG1))[0])

# ---------- btop 风格浮框 ----------
def box(top, left, wd, rows, title, foot):
    bc = sty(ACC, BG0)
    o = [at(top, left) + bc + '╭─ ' + sty(WH, BG0, B) + title + bc + ' ' +
         '─' * max(0, wd - 5 - w(title)) + '╮' + R]
    for i, segs in enumerate(rows):
        o.append(at(top+1+i, left) + bc + '│' +
                 segs_str(segs, wd-2, sty(None, BG1))[0] + bc + '│' + R)
    o.append(at(top+1+len(rows), left) + bc + '╰─ ' + sty(DIM, BG0) + foot + bc + ' ' +
             '─' * max(0, wd - 5 - w(foot)) + '╯' + R)
    return ''.join(o)

def win_switcher(sel, cur):
    wd = 46; rows = []
    rows.append([(sty(DIM, BG1), f' 会话 cosmos · {len(WINS)} 个窗口')])
    for i, (n, panes, pend) in enumerate(WINS):
        s = (i == sel); rb = ACC if s else BG1; tf = DK if s else FG
        rnd = random.Random(i * 7 + 3)
        segs = [(sty(DK if s else DIM, WH if s else BG2, B), f' {i+1} '),
                (sty(tf, rb), ' '),
                (sty(GRN if i == cur else tf, rb, B), '◆ ' if i == cur else '  '),
                (sty(tf, rb, B if s else ''), n + ' ' * (9 - w(n)))]
        lay = ''
        for p in range(panes): lay += '██' + ' '
        segs.append((sty(DK if s else DIM, rb), lay + ' ' * (12 - w(lay))))
        for k in range(8):                                    # btop 式渐变活动条
            lv = rnd.randint(1, 8) if i != 2 else 8 - k
            segs.append((sty(lerp(GRN, ORG, k / 7) if not s else DK, rb), '▁▂▃▄▅▆▇█'[lv-1]))
        segs.append((sty(tf, rb), ' '))
        segs.append((sty(DK, ORG), ' ') if pend else (sty(tf, rb), ' '))
        rows.append(segs)
    top = max(1, (PROWS - len(rows) - 2) // 2); left = max(1, (W_ - wd) // 2)
    return box(top, left, wd, rows, '窗口', '↑↓ 选择  ⏎ 切换  esc 取消')

# ---------- 图片 / PDF ----------
BGV = (14,15,20)
def clamp(x): return max(0, min(255, int(x)))
def img_color(u, v):
    if not (0 <= u < 160 and 0 <= v < 100): return BGV
    x, y = u / 160, v / 100
    a = (math.sin(x*6 + math.sin(y*5)*1.5) + math.sin(y*7 - x*3) + math.sin((x+y)*9)*.5 + 2.5) / 5
    g = max(0, 1 - ((x-.65)**2 + (y-.4)**2) * 10)
    r = 18 + 140*a*a + 120*g; gg = 14 + 50*a + 90*g; b = 40 + 150*a + 40*g
    if ((int(u)*73856093) ^ (int(v)*19349663)) % 131 == 0: r = gg = b = 240
    return (clamp(r), clamp(gg), clamp(b))
_lay = {}
def pdf_color(u, v, page):
    if not (0 <= u < 100 and 0 <= v < 141): return BGV
    if page not in _lay:
        rnd = random.Random(page); _lay[page] = [55 + rnd.random()*35 for _ in range(20)]
    if 12 <= v < 17 and 10 <= u < 60: return (40,42,54)
    if page % 3 == 0 and 15 <= u < 85 and 60 <= v < 100:
        return lerp((80,130,200), (200,120,160), (u-15)/70)
    k = v - 28
    if k >= 0:
        i = int(k // 5)
        if i < 20 and k % 5 < 2 and i % 7 != 6 and 10 <= u < 10 + _lay[page][i]: return (125,128,138)
    return (244,244,240)

def draw_view(kind, page, zoom, px, py):
    iw, ih = (160, 100) if kind == 'img' else (100, 141)
    PH = PROWS * 2; s = min(W_ / iw, PH / ih) * zoom
    col = img_color if kind == 'img' else (lambda u, v: pdf_color(u, v, page))
    o = []
    for row in range(PROWS):
        o.append(at(row+1, 1)); last = None
        for x in range(W_):
            u = (x + .5 - W_/2) / s + iw/2 + px
            t = col(u, (2*row + .5 - PH/2) / s + ih/2 + py)
            b = col(u, (2*row + 1.5 - PH/2) / s + ih/2 + py)
            if (t, b) != last:
                o.append('\x1b[38;2;%d;%d;%dm\x1b[48;2;%d;%d;%dm' % (t + b)); last = (t, b)
            o.append('▀')
        o.append(R)
    return ''.join(o)

def key(k, d): return (sty(DK, ACL, B), f' {k} '), (sty(FG, BG1), f' {d}'.ljust(14))
def help_box(kind):
    items = [('+ -', '缩放'), ('0', '适配窗口'), ('← ↑ ↓ →', '移动'), ('q / esc', '退出')]
    if kind == 'pdf': items = [('n  p', '下一页 上一页'), ('g', '跳转页码')] + items
    rows = [list(key(k, d)) for k, d in items]
    wd = 34; top = max(1, (PROWS - len(rows) - 2) // 2); left = max(1, (W_ - wd) // 2)
    return box(top, left, wd, rows, '帮助', '? 关闭')

def goto_bar(buf, total):
    segs = [(sty(DK, ORG, B), ' 跳转 '), (sty(WH, BG2, B), f' {buf}'), (sty(ACC, BG2), '▏'),
            (sty(DIM, BG2), f' / {total} ')]
    return at(PROWS, 1) + segs_str(segs, 24, sty(None, BG2))[0]

# ---------- 主循环 ----------
def main():
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    sys.stdout.write('\x1b[?1049h'); TOTAL = 18
    try:
        tty.setraw(fd)
        cr, ci, pre, hi, cands = 3, len(lines[3]), '', 0, []
        mode, cur, sel, leader = 'edit', 0, 0, False
        page, zoom, px, py, helpon, goto = 3, 1.0, 0, 0, False, None
        while True:
            o = ['\x1b[?25l']
            if mode in ('img', 'pdf'): o.append(draw_view(mode, page, zoom, px, py))
            else: o.append(draw_pane())
            o.append(status(mode, cur, leader, bool(pre), page, TOTAL))
            if mode == 'edit':
                r, c = cr + 1, w(lines[cr][:ci]) + 1
                if pre: o.append(cand_overlay(r, c, pre, cands, hi))
                else:   o.append(at(r, c) + '\x1b[?25h')
            if mode == 'win': o.append(win_switcher(sel, cur))
            if helpon: o.append(help_box(mode))
            if goto is not None: o.append(goto_bar(goto, TOTAL))
            sys.stdout.write(''.join(o)); sys.stdout.flush()
            k = os.read(fd, 32).decode(errors='ignore')
            if k == '\x03': break
            if leader:
                leader = False
                if k == 'w': mode, sel = 'win', cur
                elif k == 'i': mode, zoom, px, py, helpon = 'img', 1.0, 0, 0, False
                elif k == 'p': mode, zoom, px, py, helpon = 'pdf', 1.0, 0, 0, False
                continue
            if k == '\x01': leader = True; continue
            if mode == 'win':
                if k in ('\x1b[A', 'k'): sel = (sel - 1) % len(WINS)
                elif k in ('\x1b[B', 'j'): sel = (sel + 1) % len(WINS)
                elif k.isdigit() and 1 <= int(k) <= len(WINS): cur = int(k) - 1; mode = 'edit'
                elif k == '\r': cur = sel; mode = 'edit'
                elif k == '\x1b': mode = 'edit'
            elif mode in ('img', 'pdf'):
                if goto is not None:
                    if k.isdigit(): goto += k
                    elif k in ('\x7f', '\x08'): goto = goto[:-1]
                    elif k == '\r':
                        if goto: page = max(1, min(TOTAL, int(goto)))
                        goto = None
                    elif k == '\x1b': goto = None
                    continue
                st = 6 / zoom
                if k in ('q', '\x1b'):
                    if helpon: helpon = False
                    else: mode = 'edit'
                elif k == '?': helpon = not helpon
                elif k in ('+', '='): zoom = min(8, zoom * 1.25)
                elif k == '-': zoom = max(0.3, zoom / 1.25)
                elif k == '0': zoom, px, py = 1.0, 0, 0
                elif k in ('\x1b[D', 'h'): px -= st
                elif k in ('\x1b[C', 'l'): px += st
                elif k in ('\x1b[A', 'k'): py -= st
                elif k in ('\x1b[B', 'j'): py += st
                elif mode == 'pdf':
                    if k in ('n', '\x1b[6~', ' '): page = min(TOTAL, page + 1)
                    elif k in ('p', '\x1b[5~'): page = max(1, page - 1)
                    elif k == 'g': goto = ''
            else:
                if pre:
                    n = min(5, len(cands))
                    if k == '\x1b': pre = ''; hi = 0
                    elif k in ('\x7f', '\x08'): pre = pre[:-1]; hi = 0
                    elif k in ('\t', ']'): hi = (hi + 1) % n
                    elif k == '[': hi = (hi - 1) % n
                    elif len(k) == 1 and k.isascii() and k.isalpha(): pre += k.lower(); hi = 0
                    elif k in (' ', '\r') or (k.isdigit() and 1 <= int(k) <= n):
                        text = pre if k == '\r' else cands[hi if not k.isdigit() else int(k)-1][0]
                        lines[cr] = lines[cr][:ci] + text + lines[cr][ci:]
                        ci += len(text); pre = ''; hi = 0
                    if pre:
                        cands = DICT.get(pre, [(pre, '-')]); hi = min(hi, len(cands) - 1)
                else:
                    if   k == '\x1b[A': cr = max(0, cr - 1)
                    elif k == '\x1b[B': cr = min(PROWS - 1, cr + 1)
                    elif k == '\x1b[C': ci += 1
                    elif k == '\x1b[D': ci = max(0, ci - 1)
                    elif len(k) == 1 and k.isascii() and k.isalpha():
                        pre = k.lower(); cands = DICT.get(pre, [(pre, '-')]); hi = 0
                    ci = min(ci, len(lines[cr]))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write('\x1b[?25h\x1b[?1049l'); sys.stdout.flush()
main()
