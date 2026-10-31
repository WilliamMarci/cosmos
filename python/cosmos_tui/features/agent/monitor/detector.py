"""Bounded row differences and local repeated-frame animation evidence."""

from collections import deque
import hashlib


def rows(screen):
    return [
        hashlib.sha256(line.encode()).hexdigest()[:16]
        for line in screen["text"].splitlines()
    ]


def baseline(screen):
    return dict(
        session_id=screen.get("session_id"),
        rows=rows(screen),
        identity=[screen[k] for k in ("pid", "window_id", "pane_width", "pane_height")],
        program=screen["pane_current_command"],
    )


class Detector:
    def __init__(self, initial):
        self.previous = initial["rows"]
        self.identity = initial["identity"]
        self.history = {}
        self.changed = set()
        self.pending_since = None

    def update(self, screen, now):
        current = baseline(screen)
        if current["identity"] != self.identity:
            return dict(
                type="invalidated", reason="Terminal identity or layout changed"
            )
        changed, animated = [], []
        for index in range(max(len(self.previous), len(current["rows"]))):
            before = self.previous[index] if index < len(self.previous) else None
            after = current["rows"][index] if index < len(current["rows"]) else None
            history = self.history.setdefault(index, deque([before], maxlen=8))
            if before != after:
                changed.append(index + 1)
                if after in history and len(set(history)) > 1:
                    animated.append(index + 1)
                history.append(after)
        self.previous = current["rows"]
        self.changed.update(set(changed) - set(animated))
        self.changed.difference_update(animated)
        if changed and self.pending_since is None:
            self.pending_since = now
        if self.pending_since is not None and now - self.pending_since >= 0.3:
            result = dict(
                type="changed" if self.changed else "animation",
                rows=sorted(self.changed),
                animated_rows=animated,
                source="terminal_difference",
                confidence=1.0 if self.changed else 0.5,
            )
            self.changed.clear()
            self.pending_since = None
            return result
        return None
