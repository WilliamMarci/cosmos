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
        pane_in_mode=observation.get("pane_in_mode", False),
        alternate_screen=observation.get("alternate_screen", False),
        screen=observation.get("screen", "normal"),
        text=selected,
        blank_rows_omitted=True,
        truncated=observation["truncated"]
        or len(selected) < len(rows)
        or any(
            a["text"] != b["text"] for a, b in zip(selected, rows[-len(selected) :])
        ),
    )


def step_observation(cache, observation, *, full=False):
    """Positioned row replacements, including cleared rows; never a transcript."""
    pane = observation["pane"]
    previous = cache.get(pane)
    cache[pane] = dict(observation)
    if len(cache) > 32:
        del cache[next(iter(cache))]
    compatible = (
        previous is not None
        and all(
            previous.get(key) == observation.get(key)
            for key in (
                "dimensions",
                "region",
                "program",
                "pane_in_mode",
                "alternate_screen",
            )
        )
        and not previous.get("_delivery_truncated")
        and not previous.get("truncated")
        and not observation.get("truncated")
    )
    if full:
        return dict(observation, mode="full")
    if not compatible:
        result = dict(
            compact_snapshot(observation),
            mode="snapshot",
            full_observation_available=True,
        )
        cache[pane]["_delivery_truncated"] = result["truncated"]
        return result
    old = {row["y"]: row for row in previous["text"]}
    new = {row["y"]: row for row in observation["text"]}
    changed = [row for y, row in new.items() if old.get(y) != row]
    # Disappeared trailing capture rows clear their previous screen positions.
    changed.extend(dict(row, text="") for y, row in old.items() if y not in new)
    result = dict(observation, text=sorted(changed, key=lambda row: row["y"]))
    result = dict(
        compact_snapshot(result),
        mode="delta",
        base_snapshot_id=previous["snapshot_id"],
        full_observation_available=True,
    )
    # Blank replacements are essential; compact_snapshot omits blank rows.
    cache[pane]["_delivery_truncated"] = result["truncated"]
    result["cleared_rows"] = [row["y"] for row in changed if not row["text"].strip()]
    return result
