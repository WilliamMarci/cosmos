"""Decode one captured pane as a single SGR stream, including line boundaries."""

from functools import lru_cache
from rich.ansi import AnsiDecoder


@lru_cache(maxsize=16)
def decode_grid(lines):
    # capture-pane can carry colors/attributes across newlines. A decoder per
    # row drops that state and paints patchy backgrounds in applications.
    decoder = AnsiDecoder()
    return tuple(decoder.decode_line(line) for line in lines)
