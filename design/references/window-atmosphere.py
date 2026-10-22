import unicodedata, shutil, random
P = dict(bg=(20,22,30), base=(30,33,44), raised=(44,49,66), hi=(62,69,92),
         fg=(205,210,220), mute=(122,128,146), acc=(98,160,230), accl=(160,205,250),
         ok=(120,196,140), warn=(232,166,98), on=(16,18,26))
R = '\x1b[0m'; B = '\x1b[1m'
def sty(f=None, b=None, ex=''):
    s = R + ex
    if f: s += '\x1b[38;2;%d;%d;%dm' % P[f]
    if b: s += '\x1b[48;2;%d;%d;%dm' % P[b]
    return s
def lerp(a, b, t): return tuple(int(P[a][i] + (P[b][i]-P[a][i])*t) for i in range(3))
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
def fill(segs, width, padbg):                 # 补位色由调用者指定 = 行自己的底色
    o, used = '', 0
    for st, tx in segs:
        tx = clip(tx, width - used); o += st + tx; used += w(tx)
    return o + sty(None, padbg) + ' ' * (width - used) + R

WD = min(shutil.get_terminal_size().columns, 72); IW = WD - 2
SEL = 1; CUR = 1
WINS = [('shell',1,False),('vim',2,False),('agent',1,True),('logs',3,False),('docs',2,False)]
BC = sty('acc', 'base')                       # 边框: 与内部同一底色 base

def border_top(t):
    return BC + '╭─ ' + sty('fg','base',B) + t + BC + ' ' + '─'*(WD-5-w(t)) + '╮' + R
def border_bot(t):
    return BC + '╰─ ' + sty('mute','base') + t + BC + ' ' + '─'*(WD-5-w(t)) + '╯' + R
def row(segs, padbg): return BC + '│' + fill(segs, IW, padbg) + BC + '│' + R

out = [border_top('窗口')]
out.append(row([(sty('mute','base'), ' 会话 cosmos  共 5 个')], 'base'))
for i, (n, panes, pend) in enumerate(WINS):
    s = i == SEL; rb = 'acc' if s else 'base'; tf = 'on' if s else 'fg'
    rnd = random.Random(i*7+3)
    segs = [(sty('on' if s else 'mute', 'accl' if s else 'hi', B), f' {i+1} '),
            (sty(None, rb), ' '),
            (sty(None,'ok'), ' ') if i == CUR else (sty(None, rb), ' '),
            (sty(tf, rb, B if s else ''), ' ' + n + ' '*(10-w(n)))]
    for p in range(panes):
        segs += [(sty(None, 'on' if s else 'mute'), '  '), (sty(None, rb), ' ')]
    segs.append((sty(None, rb), ' '*(3*(3-panes)+2)))
    for k in range(8):
        lv = (1-k/8) if i == 2 else rnd.random()
        c = lerp('ok','warn',k/7); b0 = P[rb]
        mix = tuple(int(b0[j] + (c[j]-b0[j])*(.1+.9*lv)) for j in range(3))
        segs.append(('\x1b[48;2;%d;%d;%dm' % mix, ' '))
    segs.append((sty(None, rb), ' '))
    segs.append((sty(None,'warn'), ' ') if pend else (sty(None, rb), ' '))
    out.append(row(segs, rb))                 # 选中行用蓝色补位 -> 铺满到右边框

# 预览区: 靠底色分隔, 不画线
out.append(row([(sty('on','acc',B), ' 预览 '), (sty('fg','raised'), ' vim  2 个窗格 ')], 'raised'))
lw = (IW-1)//2; rw = IW-1-lw
L = ["def draw_overlay(c, cur):", "    top = cur.y + 1", "    if top + 2 > c.rows:", "        top = cur.y - 2"]
Rt = ["# notes", "- hook: screen-redraw", "- ime: client layer", "- todo: pdf cache"]
def pcell(txt, wd): return fill([(sty('fg','bg'), ' ' + txt)], wd, 'bg')
tl = fill([(sty('on','acc',B), ' %0 '), (sty('on','accl'), ' vim ')], lw, 'acc')
tr = fill([(sty('mute','raised'), ' %1 '), (sty('mute','raised'), ' vim ')], rw, 'raised')
out.append(BC + '│' + tl + sty(None,'base') + ' ' + tr + BC + '│' + R)
for a, b in zip(L, Rt):
    out.append(BC + '│' + pcell(a, lw) + sty(None,'base') + ' ' + pcell(b, rw) + BC + '│' + R)
out.append(border_bot('j k 选择   Enter 切换   Esc 取消'))
print('\n' + '\n'.join(out) + '\n')
