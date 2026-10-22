"""One output owner: graphics are part of Textual CompositorUpdate batches.
Pinned to Textual 8.2.8 because _display / CompositorUpdate are private APIs.
No sys.stdout, tty writes, alternate-screen management or second render loop here.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os

from textual._compositor import CompositorUpdate


class Batch(CompositorUpdate):
    def __init__(self, inner=None, suffix=""):
        self.inner, self.suffix = inner, suffix

    def render_segments(self, console):
        return (self.inner.render_segments(console) if self.inner else "") + self.suffix


class Graphics:
    def __init__(self):
        mode = os.getenv("COSMOS_GRAPHICS", "")
        term = os.getenv("TERM", "").lower()
        self.enabled = mode == "kitty" or (
            mode != "text" and ("kitty" in term or term == "xterm-ghostty")
        )
        self.images = {}
        self.sources = {}
        self.pending = ""
        self.next = (os.getpid() * 1024) & 0xFFFFFFFF

    def commit(self, images):
        wanted = {}
        sources = {}
        for key, image, x, y in images:
            sources[key] = (image, x, y)
            previous = self.sources.get(key)
            if previous and previous[0] is image and previous[1:] == (x, y):
                wanted[key] = self.images[key]
                continue
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            data = stream.getvalue()
            fingerprint = hashlib.sha256(data).digest(), x, y
            old = self.images.get(key)
            if old and old[0] == fingerprint:
                wanted[key] = old
                continue
            if old:
                self.pending += f"\x1b_Ga=d,d=I,i={old[1]},q=2\x1b\\"
            self.next = (self.next + 1) & 0xFFFFFFFF or 1
            image_id = self.next
            encoded = base64.b64encode(data).decode()
            self.pending += f"\x1b[{y + 1};{x + 1}H"
            for i in range(0, len(encoded), 4096):
                m = int(i + 4096 < len(encoded))
                header = (
                    f"a=T,f=100,i={image_id},q=2,C=1,z=-1,m={m}" if i == 0 else f"m={m}"
                )
                self.pending += f"\x1b_G{header};{encoded[i : i + 4096]}\x1b\\"
            wanted[key] = fingerprint, image_id
        for key, (_, image_id) in self.images.items():
            if key not in wanted:
                self.pending += f"\x1b_Ga=d,d=I,i={image_id},q=2\x1b\\"
        self.images = wanted
        self.sources = sources

    def take(self):
        result = self.pending
        self.pending = ""
        return result


def halfblocks(image, width, height):
    from rich.text import Text

    small = image.resize((max(1, width), max(1, height * 2)))
    lines = []
    for y in range(height):
        text = Text()
        for x in range(width):
            a = small.getpixel((x, y * 2))
            b = small.getpixel((x, y * 2 + 1))
            text.append(
                "▀", style=f"rgb({a[0]},{a[1]},{a[2]}) on rgb({b[0]},{b[1]},{b[2]})"
            )
        lines.append(text)
    return lines
