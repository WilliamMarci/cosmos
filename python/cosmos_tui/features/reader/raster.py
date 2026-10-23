"""Adaptive PDF rasterization: reduce resolution, never reject a compressed page by size."""

import io
import math
import time
from PIL import Image


def render_pdf(path, page, tool, edge=2400, megabytes=32):
    target = min(int(edge), 4000)
    budget = int(megabytes) * 1024**2
    last = None
    deadline = time.monotonic() + 30
    for _ in range(4):
        if time.monotonic() > deadline:
            break
        try:
            data = tool(
                "pdftoppm",
                "-f",
                str(page),
                "-l",
                str(page),
                "-singlefile",
                "-scale-to",
                str(target),
                "-png",
                str(path),
            )
            with Image.open(io.BytesIO(data)) as opened:
                pixels = opened.width * opened.height
                ratio = min(1, math.sqrt(min(16_000_000, budget // 3) / max(1, pixels)))
                if (ratio < 1 or len(data) > budget) and target > 600:
                    target = max(600, int(target * min(0.75, ratio)))
                    continue
                if pixels > 16_000_000 or len(data) > budget or pixels * 3 > budget:
                    raise ValueError("PDF raster exceeds budget at minimum resolution")
                return opened.convert("RGB"), target
        except (ValueError, Image.DecompressionBombError, RuntimeError) as error:
            last = error
            if target <= 600:
                break
            target = max(600, target // 2)
    raise RuntimeError(
        f"PDF page could not be rendered after reducing resolution: {last}"
    )
