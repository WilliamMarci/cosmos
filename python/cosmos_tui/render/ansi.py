"""Decode one captured pane as a single SGR stream, including line boundaries."""

from functools import lru_cache

from rich.ansi import AnsiDecoder


@lru_cache(maxsize=16)
def decode_grid(lines):
    # capture-pane can carry colors/attributes across newlines. A decoder per
    # row drops that state and paints patchy backgrounds in applications.
    decoder = AnsiDecoder()
    rows = []
    for line in lines:
        text = decoder.decode_line(line)
        # Tmux captures preserve HT. Expand from pane-local display columns
        # before Strip measures/crops them; raw HT is otherwise zero-width to
        # Rich but moves the outer terminal cursor and displaces adjacent panes.
        text.expand_tabs(8)
        rows.append(text)
    return tuple(rows)
