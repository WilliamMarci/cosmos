#!/usr/bin/env python3
"""Real PTYs and backend: inline Kitty data, PDF search, overlays and reconnect."""

import base64
import fcntl
import json
import os
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "target/release/cosmos"


def png(path, red=220):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = b"".join(b"\x00" + bytes([red, 40 + y * 2, 60]) * 60 for y in range(40))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 60, 40, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def pdf(path):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>",
    ]
    for page, text in enumerate(["First page", "Second page", "Search target here"]):
        stream = f"BT /F1 22 Tf 40 180 Td ({text}) Tj ET".encode()
        objects += [
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] /Resources << /Font << /F1 9 0 R >> >> /Contents {4 + page * 2} 0 R >>".encode(),
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream",
        ]
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{x:010} 00000 n \n".encode() for x in offsets[1:])
    out += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    path.write_bytes(out)


with tempfile.TemporaryDirectory(prefix="cosmos-viewer-") as tmp:
    tmp = Path(tmp)
    png(tmp / "sample.png")
    pdf(tmp / "sample.pdf")
    env = dict(
        os.environ,
        XDG_RUNTIME_DIR=str(tmp),
        XDG_CONFIG_HOME=str(tmp / "config"),
        XDG_STATE_HOME=str(tmp / "state"),
        XDG_CACHE_HOME=str(tmp / "cache"),
        COSMOS_TMUX_SOCKET=f"cosmos-viewer-{os.getpid()}",
        COSMOS_GRAPHICS="kitty",
        TERM="xterm-kitty",
        HISTFILE="/dev/null",
        LC_ALL="C",
    )
    daemon = subprocess.Popen([str(BIN), "daemon"], env=env)
    clients = []
    handles = []
    buf = bytearray()

    def tmux(*args):
        return subprocess.run(
            ["tmux", "-L", env["COSMOS_TMUX_SOCKET"], *args],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def pump(fd, seconds=0.3):
        end = time.monotonic() + seconds
        out = b""
        while time.monotonic() < end:
            if select.select([fd], [], [], 0.02)[0]:
                try:
                    part = os.read(fd, 65536)
                except OSError:
                    break
                out += part
                buf.extend(part)
        return out

    def wait(fd, token, timeout=12):
        out = b""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            out += pump(fd, 0.05)
            if token in out:
                return out
        raise AssertionError(f"missing {token!r}: {out[-400:]!r}")

    def launch(command=None, graphics="kitty"):
        fd, slave = pty.openpty()
        handles.extend([fd, slave])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 800, 480))
        original = termios.tcgetattr(slave)
        process = subprocess.Popen(
            [str(BIN), *(command or ["workspace"])],
            env=dict(env, COSMOS_GRAPHICS=graphics),
            stdin=slave,
            stdout=slave,
            stderr=slave,
        )
        clients.append(process)
        return process, fd, slave, original

    def wire():
        raw = tmux("show-options", "-pv", "-t", "main", "@cosmos_viewer")
        return json.loads(base64.b64decode(raw))

    def until(fn):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            if fn():
                return
            time.sleep(0.05)
        raise AssertionError("condition timeout")

    try:
        until(lambda: (tmp / "cosmos/control.sock").exists())
        process, fd, slave, original = launch()
        wait(fd, b"cosmos ")
        # The CLI runs on the working host, sends a pane request and returns immediately.
        os.write(
            fd, f"export VIEW_KEEP=alive; '{BIN}' open '{tmp}/sample.png'\r".encode()
        )
        wait(fd, b"\x1b_Ga=T,f=24")
        pump(fd)
        assert b"t=f" not in buf and b"t=t" not in buf
        assert b"zoom" not in buf.lower(), "shortcut descriptions must remain hidden"
        packets = re.findall(rb"\x1b_G([^;]*);([^\x1b]*)\x1b\\", bytes(buf))
        chunks = []
        dims = None
        for header, data in packets:
            if b"a=T" in header:
                chunks = []
                dims = tuple(
                    int(re.search(key + rb"=(\d+)", header).group(1))
                    for key in [b"s", b"v"]
                )
            if data:
                chunks.append(data)
            if b"m=0" in header and chunks:
                pixels = base64.b64decode(b"".join(chunks))
                assert len(pixels) == dims[0] * dims[1] * 3
                assert len(set(pixels)) > 3
        assert dims and len(pixels) > 100000
        assert b"a=T" not in pump(fd, 0.5), "idle viewer must not retransmit pixels"
        png(tmp / "sample.png", 120)
        wait(fd, b"\x1b_Ga=T,f=24")
        pump(fd)
        os.write(fd, b"\x02c")
        wait(fd, b"\x1b_Ga=d")
        pump(fd)
        os.write(fd, b"\x02b")
        wait(fd, b"\x1b_Ga=T,f=24")
        pump(fd)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 100, 1000, 560))
        wait(fd, b"\x1b_Ga=T,f=24")
        pump(fd)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 800, 480))
        wait(fd, b"\x1b_Ga=T,f=24")
        pump(fd)

        before = tmux(
            "display-message", "-p", "-t", "main", "#{pane_width} #{pane_height}"
        )
        os.write(fd, b"\x02?")
        wait(fd, b"Viewer")
        wait(
            fd, b"confirm / cancel search"
        ) if b"confirm / cancel search" not in buf else None
        os.write(fd, b"\x1b")
        pump(fd)
        os.write(fd, b"+")
        pump(fd)
        until(lambda: wire()["zoom"] > 1)
        # Wheel zoom and drag are decoded as events, never leaked to Bash.
        os.write(fd, b"\x1b[<80;10;10M")
        pump(fd)
        until(lambda: wire()["zoom"] > 1.3)
        os.write(fd, b"\x1b[<0;10;10M\x1b[<32;12;11M\x1b[<0;12;11m")
        pump(fd)
        assert wire()["pan"] != [0, 0]
        os.write(fd, b"\x02d")
        assert process.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        process, fd, slave, original = launch()
        wait(fd, b"\x1b_Ga=T,f=24")
        pump(fd)
        assert wire()["zoom"] > 1
        os.write(fd, b"q")
        pump(fd)
        assert (
            tmux("display-message", "-p", "-t", "main", "#{pane_width} #{pane_height}")
            == before
        )
        os.write(fd, b"printf 'restored:%s\\n' \"$VIEW_KEEP\"\r")
        wait(fd, b"restored:alive")
        os.write(fd, f"'{BIN}' open '{tmp}/sample.pdf'\r".encode())
        wait(fd, b"1 / 3")
        pump(fd)
        os.write(fd, b"]")
        wait(fd, b"2 / 3")
        pump(fd)
        os.write(fd, b"/target\r")
        wait(fd, b"3 / 3")
        pump(fd)
        until(lambda: wire()["page"] == 3)
        assert b"1 matches" in buf
        assert len(list((tmp / "cache/cosmos/viewer").glob("*.png"))) >= 2
        chunks = []
        pixels = b""
        for header, data in re.findall(rb"\x1b_G([^;]*);([^\x1b]*)\x1b\\", bytes(buf)):
            if b"a=T" in header:
                chunks = []
                dims = tuple(
                    int(re.search(key + rb"=(\d+)", header).group(1))
                    for key in [b"s", b"v"]
                )
            if data:
                chunks.append(data)
            if b"m=0" in header and chunks:
                pixels = base64.b64decode(b"".join(chunks))
        highlight = sum(
            r > 180 and g > 130 and b < 140
            for r, g, b in zip(pixels[::3], pixels[1::3], pixels[2::3])
        )
        assert highlight > 100, "search must visibly highlight PDF text"
        if os.environ.get("COSMOS_VIEWER_PROOF"):

            def chunk(kind, data):
                return (
                    struct.pack(">I", len(data))
                    + kind
                    + data
                    + struct.pack(">I", zlib.crc32(kind + data))
                )

            rows = b"".join(
                b"\0" + pixels[y * dims[0] * 3 : (y + 1) * dims[0] * 3]
                for y in range(dims[1])
            )
            Path(os.environ["COSMOS_VIEWER_PROOF"]).write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", *dims, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows))
                + chunk(b"IEND", b"")
            )

        # Output is retained while the viewer occupies the pane.
        tmux("send-keys", "-t", "main", "printf 'background:%s\\n' retained", "Enter")
        pump(fd)
        os.write(fd, b"q")
        wait(fd, b"background:retained")
        pump(fd)
        os.write(fd, b"\x02d")
        assert process.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        process, fd, slave, original = launch(
            ["view", str(tmp / "sample.png")], graphics="text"
        )
        wait(fd, "▀".encode())
        os.write(fd, b"?")
        wait(fd, b"Viewer")
        os.write(fd, b"\x1bq")
        pump(fd)
        assert process.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        assert list((tmp / "cache/cosmos/viewer").glob("*.png"))
        subprocess.run([str(BIN), "cache-clear"], env=env, check=True)
        assert not (tmp / "cache/cosmos/viewer").exists()
        print(
            json.dumps(
                dict(
                    inline_kitty=True,
                    pdf_pages=True,
                    pdf_cross_page_search=True,
                    search_highlight=True,
                    quiet_context_help=True,
                    mouse=True,
                    reconnect_view=True,
                    background_retained=True,
                    text_fallback=True,
                    terminal_restore=True,
                    cache_clear=True,
                    source_reload=True,
                    window_graphics_cleanup=True,
                    resize=True,
                    idle_no_retransmit=True,
                )
            )
        )
    except Exception:
        print("client status", [(p.pid, p.poll()) for p in clients])
        clean = re.sub(rb"\x1b_G.*?\x1b\\", b"", bytes(buf), flags=re.S)
        clean = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", clean)
        print("terminal text tail", clean[-2500:])
        print(
            "geometry",
            tmux(
                "display-message",
                "-p",
                "-t",
                "main",
                "#{pane_width} #{pane_height} #{client_width} #{client_height}",
            ),
        )
        print("backend", tmux("capture-pane", "-p", "-t", "main"))
        print("option", tmux("show-options", "-p", "-t", "main"))
        raise
    finally:
        for p in clients:
            if p.poll() is None:
                p.terminate()
        for p in clients:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        subprocess.run(
            ["tmux", "-L", env["COSMOS_TMUX_SOCKET"], "kill-server"],
            env=env,
            capture_output=True,
        )
        subprocess.run([str(BIN), "stop"], env=env, capture_output=True)
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon.kill()
            daemon.wait()
        for fd in handles:
            os.close(fd)
