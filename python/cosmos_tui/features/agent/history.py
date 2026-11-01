"""Bounded, immutable scrollback snapshots with small searchable pages."""

from collections import OrderedDict
import secrets
import time


class HistoryTools:
    async def read_history(self, pane, limit=100, query=None, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be 1–200 rows")
        if query is not None and (not isinstance(query, str) or len(query) > 256):
            raise ValueError("query must be at most 256 characters")
        if query and self.redact(query) != query:
            raise ValueError("Do not query managed credentials")
        row = await self.pane(pane)  # Also recheck privacy on every continuation.
        if not hasattr(self, "_history"):
            self._history = OrderedDict()
        for identity in list(self._history):
            if time.monotonic() - self._history[identity]["created"] > 300:
                del self._history[identity]
        if cursor is None:
            size = int(
                await self.backend.cli(
                    "display-message", "-p", "-t", pane, "#{history_size}"
                )
            )
            count = min(size, 20000)
            text = (
                await self.backend.cli(
                    "capture-pane", "-p", "-t", pane, "-S", str(-count), "-E", "-1"
                )
                if count
                else ""
            )
            fresh = await self.pane(pane)
            if fresh["pid"] != row["pid"]:
                raise ValueError("Tmux service changed during history capture")
            raw = self.redact(text).encode()
            cut = len(raw) > 2 * 1024**2
            text = raw[-2 * 1024**2 :].decode("utf-8", errors="ignore")
            lines = text.splitlines()
            if cut and lines:
                lines = lines[1:]  # Discard a potentially partial oldest row.
            indexed = [
                dict(line=i - len(lines), text=line) for i, line in enumerate(lines)
            ]
            indexed.reverse()  # Newest page first; each returned page remains chronological.
            if query:
                indexed = [
                    r for r in indexed if query.casefold() in r["text"].casefold()
                ]
            identity, offset = secrets.token_hex(16), 0
            self._history[identity] = dict(
                pane=pane,
                created=time.monotonic(),
                rows=indexed,
                query=query,
                history_size=size,
                server_pid=row["pid"],
                history_truncated=size > count or cut,
            )
            while len(self._history) > 4:
                self._history.popitem(last=False)
        else:
            if not isinstance(cursor, str) or len(cursor) > 64:
                raise ValueError("invalid history cursor")
            try:
                identity, position = cursor.split(":")
                offset = int(position)
                entry = self._history[identity]
            except (ValueError, KeyError):
                raise ValueError("History snapshot expired; start a new read") from None
            if (
                entry["pane"] != pane
                or offset < 0
                or offset > len(entry["rows"])
                or query not in (None, entry["query"])
            ):
                raise ValueError("cursor does not match this pane/query")
        entry = self._history[identity]
        if entry["server_pid"] != row["pid"]:
            raise ValueError("Tmux service changed; start a new history read")
        rows, used = [], 0
        for item in entry["rows"][offset : offset + limit]:
            raw = item["text"].encode()
            if rows and used + len(raw) > 16384:
                break
            clipped = raw[:16384].decode("utf-8", errors="ignore")
            rows.append(dict(item, text=clipped, truncated=clipped != item["text"]))
            used += len(clipped.encode())
        following = offset + len(rows)
        rows.reverse()
        return dict(
            pane=pane,
            snapshot_id=identity,
            history_size=entry["history_size"],
            history_truncated=entry["history_truncated"],
            query=entry["query"],
            rows=rows,
            next_cursor=f"{identity}:{following}"
            if following < len(entry["rows"])
            else None,
            coordinate_space="immutable_scrollback_rows_negative_from_viewport",
            current_screen_included=False,
        )
