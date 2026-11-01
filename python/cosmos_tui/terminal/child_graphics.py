"""Extract Kitty graphics from tmux control-mode pane output.

Tmux control mode reports pane output as octal-escaped `%output` blocks.  A
program that uses Kitty graphics may emit either a direct APC sequence or a
tmux passthrough DCS wrapper around it.  Cosmos owns the outer terminal, so it
must forward the inner graphics itself; `capture-pane` only returns the cell
grid (including Kitty unicode placeholders).
"""

from __future__ import annotations

KITTY_PREFIX = b"\x1b_G"
TMUX_PREFIX = b"\x1bPtmux;"
ST = b"\x1b\\"
MAX_BUFFER = 32 * 1024 * 1024


def unescape_output(data: bytes) -> bytes:
    """Undo tmux control-mode octal escaping for one `%output` payload."""
    result = bytearray()
    index = 0
    while index < len(data):
        if (
            data[index] == 0x5C
            and index + 3 < len(data)
            and all(0x30 <= byte <= 0x37 for byte in data[index + 1 : index + 4])
        ):
            result.append(int(data[index + 1 : index + 4], 8))
            index += 4
        else:
            result.append(data[index])
            index += 1
    return bytes(result)


def _direct_sequences(data: bytes) -> list[bytes]:
    sequences = []
    index = 0
    while True:
        start = data.find(KITTY_PREFIX, index)
        if start < 0:
            return sequences
        end = data.find(ST, start + len(KITTY_PREFIX))
        if end < 0:
            return sequences
        sequences.append(data[start : end + len(ST)])
        index = end + len(ST)


class KittyStream:
    """Incrementally split one pane's output into complete Kitty APC sequences."""

    def __init__(self):
        self.buffer = b""

    def feed(self, data: bytes, final=False) -> list[bytes]:
        self.buffer += data
        sequences = []
        try:
            while True:
                direct = self.buffer.find(KITTY_PREFIX)
                wrapped = self.buffer.find(TMUX_PREFIX)
                starts = [position for position in (direct, wrapped) if position >= 0]
                if not starts:
                    self._retain_partial_prefix()
                    return sequences
                start = min(starts)
                if start:
                    self.buffer = self.buffer[start:]
                if self.buffer.startswith(TMUX_PREFIX):
                    end = self._outer_terminator(len(TMUX_PREFIX))
                    if end is None:
                        return sequences
                    payload = self.buffer[len(TMUX_PREFIX) : end]
                    self.buffer = self.buffer[end + len(ST) :]
                    payload = payload.replace(b"\x1b\x1b", b"\x1b")
                    sequences.extend(_direct_sequences(payload))
                else:
                    end = self.buffer.find(ST, len(KITTY_PREFIX))
                    if end < 0:
                        return sequences
                    sequences.append(self.buffer[: end + len(ST)])
                    self.buffer = self.buffer[end + len(ST) :]
        finally:
            if len(self.buffer) > MAX_BUFFER or (final and self.buffer):
                self.buffer = b""

    def _retain_partial_prefix(self):
        for prefix in (TMUX_PREFIX, KITTY_PREFIX):
            for size in range(min(len(prefix) - 1, len(self.buffer)), 0, -1):
                if self.buffer.endswith(prefix[:size]):
                    self.buffer = self.buffer[-size:]
                    return
        self.buffer = b""

    def _outer_terminator(self, start):
        index = start
        while True:
            end = self.buffer.find(ST, index)
            if end < 0:
                return None
            # An inner ST in a passthrough payload has a doubled ESC.  Only a
            # single ESC immediately before the backslash ends the outer DCS.
            if end > 0 and self.buffer[end - 1 : end] == b"\x1b":
                index = end + len(ST)
                continue
            return end
