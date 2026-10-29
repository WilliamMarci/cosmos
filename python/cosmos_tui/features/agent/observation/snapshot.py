"""Bounded text/styled-grid observations and explicitly inferred controls."""

from collections import OrderedDict
import hashlib
import json
import re
import time

from rich.cells import cell_len
from rich.console import Console
from rich.segment import Segment

from cosmos_tui.render.ansi import decode_grid

LAYERS = {"text", "presentation", "controls"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def cell_slice(text, left, width):
    """Crop by terminal cells, preserving Unicode widths and ANSI styles."""
    console = Console(color_system="truecolor")
    segments = list(
        console.render(
            text, console.options.update(width=max(1, text.cell_len), no_wrap=True)
        )
    )
    return (
        list(Segment.divide(segments, [left, left + width]))[-1]
        if left
        else list(Segment.divide(segments, [width]))[0]
    )


def build(row, raw, layers, region=None):
    width, height = row["pane_width"], row["pane_height"]
    region = dict(x=1, y=1, width=width, height=height) if region is None else region
    if set(region) != {"x", "y", "width", "height"} or any(
        type(v) is not int for v in region.values()
    ):
        raise ValueError(
            "region requires integer x, y, width and height in one-based cells"
        )
    x, y, w, h = (region[k] for k in ("x", "y", "width", "height"))
    if min(x, y, w, h) < 1 or x + w - 1 > width or y + h - 1 > height:
        raise ValueError("region is outside the application content area")
    lines, styled, controls = [], [], []
    decoded = decode_grid(tuple(raw.splitlines()))
    for index in range(y - 1, min(y + h - 1, len(decoded))):
        segments = cell_slice(decoded[index], x - 1, w)
        spans = []
        column = x
        for segment in segments:
            text = segment.text.rstrip("\n")
            if not text:
                continue
            style = segment.style
            spans.append(dict(x=column, text=text, style=str(style) if style else ""))
            column += cell_len(text)
        plain = "".join(span["text"] for span in spans)
        lines.append(dict(y=index + 1, x=x, text=plain))
        styled.append(dict(y=index + 1, spans=spans))
        for match in re.finditer(r"\[\s*([^\[\]\n]{1,40}?)\s*\]", plain):
            label = match[1].strip()
            if not label:
                continue
            rect = dict(
                x=x + cell_len(plain[: match.start()]),
                y=index + 1,
                width=cell_len(match[0]),
                height=1,
            )
            evidence = dict(text=match[0], region=rect)
            controls.append(
                dict(
                    id=digest(evidence)[:20],
                    role="button_candidate",
                    name=label,
                    source="terminal_inference",
                    confidence=0.5,
                    region=rect,
                    evidence=evidence,
                    actions=[],
                )
            )
    data = dict(
        pane=row["pane_id"],
        region=region,
        dimensions=dict(width=width, height=height),
        cursor=dict(x=row["cursor_x"] + 1, y=row["cursor_y"] + 1),
        program=row["pane_current_command"],
    )
    data["snapshot_id"] = digest(dict(data, grid=styled))
    data["observed_at"] = time.time()
    data["coordinate_space"] = "application_content_cells_1based"
    data["capabilities"] = dict(
        text=True,
        styled_grid=True,
        image=False,
        controls="terminal_inference",
        act=False,
    )
    data["truncated"] = False
    if "text" in layers:
        data["text"] = lines
    if "presentation" in layers:
        data["presentation"] = dict(rows=styled, image_contents=False)
    if "controls" in layers:
        data["controls"] = controls
    return data


class Observations:
    """Per-tool-server snapshot identities; no retained terminal transcript cache."""

    def __init__(self):
        self.known = OrderedDict()

    def finish(self, result, since=None):
        identity = result["snapshot_id"]
        result["unchanged"] = identity == since and since in self.known
        result["since_known"] = since in self.known if since else False
        self.known[identity] = True
        self.known.move_to_end(identity)
        while len(self.known) > 32:
            self.known.popitem(last=False)
        return result
