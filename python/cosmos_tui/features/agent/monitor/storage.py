"""Private persisted watch conditions and compact evidence, not transcripts."""

from contextlib import contextmanager
import json
import os
import secrets
import sqlite3
import time

from cosmos_tui.features.agent.control import location


class Watches:
    def __init__(self, socket):
        self.path = location(socket).with_suffix(".monitor.sqlite3")

    @contextmanager
    def connection(self):
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(descriptor).st_uid != os.getuid():
                raise PermissionError("Watch database belongs to another user")
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, pane TEXT, kind TEXT, needle TEXT, deadline REAL, state TEXT, baseline TEXT, result TEXT, created REAL)"
        )
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, pane, kind, needle, seconds, baseline):
        identity = "watch_" + secrets.token_hex(12)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT count(*) FROM watches WHERE state='waiting'"
                ).fetchone()[0]
                >= 32
            ):
                raise ValueError("At most 32 terminal watches may wait in one service")
            db.execute(
                "INSERT INTO watches VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    pane,
                    kind,
                    needle,
                    time.time() + seconds,
                    "waiting",
                    json.dumps(baseline),
                    None,
                    time.time(),
                ),
            )
            db.execute(
                "DELETE FROM watches WHERE id IN (SELECT id FROM watches WHERE state!='waiting' ORDER BY created DESC LIMIT -1 OFFSET 512)"
            )
        return identity

    def list(self, pending=False):
        with self.connection() as db:
            query = (
                "SELECT * FROM watches"
                + (" WHERE state='waiting'" if pending else "")
                + " ORDER BY created DESC LIMIT 544"
            )
            result = [dict(row) for row in db.execute(query)]
        for row in result:
            row["baseline"] = json.loads(row["baseline"])
            row["result"] = json.loads(row["result"]) if row["result"] else None
        return result

    def finish(self, identity, state, evidence):
        evidence = dict(
            evidence, task_complete=False, model_woken=False, observed_at=time.time()
        )
        with self.connection() as db:
            return (
                db.execute(
                    "UPDATE watches SET state=?,result=? WHERE id=? AND state='waiting'",
                    (state, json.dumps(evidence), identity),
                ).rowcount
                == 1
            )
