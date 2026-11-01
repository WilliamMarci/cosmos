"""Wall-clock schedules: one catch-up, first fold, advance across DST gaps."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import re
import time


def host_zone():
    candidates = [os.getenv("TZ", "")]
    try:
        candidates.append(
            str(Path("/etc/localtime").resolve()).split("/zoneinfo/", 1)[1]
        )
    except (OSError, IndexError):
        pass
    for candidate in candidates + ["UTC"]:
        try:
            ZoneInfo(candidate)
            return candidate
        except (ValueError, KeyError):
            pass


def wall_time(day, hour, minute, zone):
    target = datetime.combine(day, datetime.min.time()).replace(
        hour=hour, minute=minute
    )
    for _ in range(181):
        valid = []
        for fold in (0, 1):
            stamp = target.replace(tzinfo=zone, fold=fold).timestamp()
            if datetime.fromtimestamp(stamp, zone).replace(tzinfo=None) == target:
                valid.append(stamp)
        if valid:
            return min(valid)
        target += timedelta(minutes=1)
    raise ValueError("Daily time has no valid local instant")


def next_daily(spec, after):
    zone = ZoneInfo(spec["timezone"])
    hour, minute = map(int, spec["daily"].split(":"))
    day = datetime.fromtimestamp(after, zone).date()
    for offset in range(3):
        stamp = wall_time(day + timedelta(days=offset), hour, minute, zone)
        if stamp > after:
            return stamp
    raise ValueError("Cannot determine next daily occurrence")


def normalize(spec, now=None):
    now = time.time() if now is None else now
    if (
        not isinstance(spec, dict)
        or len(set(spec) & {"after_seconds", "at", "interval_seconds", "daily"}) != 1
    ):
        raise ValueError(
            "schedule needs exactly one of after_seconds/at/interval_seconds/daily"
        )
    kind = next(
        k for k in ("after_seconds", "at", "interval_seconds", "daily") if k in spec
    )
    if set(spec) - {kind, "timezone"}:
        raise ValueError("unknown schedule fields")
    if kind in ("after_seconds", "interval_seconds"):
        value = spec[kind]
        if type(value) not in (int, float) or not 1 <= value <= 366 * 86400:
            raise ValueError("schedule seconds must be 1–31622400")
        return {kind: value}, now + value
    if kind == "at":
        if not isinstance(spec[kind], str):
            raise ValueError("at must be an ISO timestamp")
        value = datetime.fromisoformat(spec[kind].replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError("at must include an explicit timezone offset")
        return {kind: value.isoformat()}, value.timestamp()
    if not isinstance(spec[kind], str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", spec[kind]
    ):
        raise ValueError("daily must be HH:MM")
    result = dict(daily=spec[kind], timezone=spec.get("timezone") or host_zone())
    ZoneInfo(result["timezone"])
    return result, next_daily(result, now)


def following(spec, due, now):
    if "interval_seconds" in spec:
        interval = spec["interval_seconds"]
        return due + (int(max(0, now - due) // interval) + 1) * interval
    if "daily" in spec:
        return next_daily(spec, now)
    return None
