"""Small positioned snapshots; truncation never changes the observed identity."""


def compact_snapshot(observation, max_bytes=4096, max_rows=24):
    rows = [
        dict(row, text=row["text"].rstrip())
        for row in observation["text"]
        if row["text"].strip()
    ]
    selected, used = [], 0
    for row in reversed(rows[-max_rows:]):
        raw = row["text"].encode("utf-8")
        available = max_bytes - used
        if available <= 0:
            break
        selected.append(
            dict(row, text=raw[:available].decode("utf-8", errors="ignore"))
        )
        used += min(len(raw), available)
    selected.reverse()
    return dict(
        snapshot_id=observation["snapshot_id"],
        pane=observation["pane"],
        dimensions=observation["dimensions"],
        cursor=observation["cursor"],
        region=observation["region"],
        coordinate_space=observation["coordinate_space"],
        text=selected,
        blank_rows_omitted=True,
        truncated=observation["truncated"]
        or len(selected) < len(rows)
        or any(
            a["text"] != b["text"] for a, b in zip(selected, rows[-len(selected) :])
        ),
    )
