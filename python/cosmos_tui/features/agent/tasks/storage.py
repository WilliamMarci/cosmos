"""Private SQLite task ledger. Model credentials and control tokens are not stored."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from cosmos_tui.features.agent.profile import profile_root, private_directory

DEFAULTS = dict(max_models=2, wake_interval_ms=2000, run_timeout_seconds=300)


def task_home():
    return Path(os.getenv("COSMOS_TASKS_HOME", profile_root() / "tasks"))


class Tasks:
    def __init__(self, socket):
        self.socket = socket
        self.path = task_home() / (
            hashlib.sha256(socket.encode()).hexdigest()[:24] + ".sqlite3"
        )

    @contextmanager
    def db(self):
        private_directory(self.path.parent)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_uid != os.getuid():
                raise PermissionError("Task database belongs to another user")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.executescript("""
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, conversation TEXT, runtime TEXT,
            pane TEXT, server_pid TEXT, session_id TEXT, goal TEXT, kind TEXT, schedule TEXT,
            next_run REAL, state TEXT, mode TEXT, watch_id TEXT, pending TEXT, run_id TEXT,
            last_wake REAL DEFAULT 0, revision INTEGER DEFAULT 0, result TEXT, updated REAL);
          CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, task TEXT, state TEXT, event TEXT,
            started REAL, finished REAL, detail TEXT);
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE IF NOT EXISTS conversation_pauses(conversation TEXT PRIMARY KEY,reason TEXT);
          CREATE TABLE IF NOT EXISTS conversation_chats(conversation TEXT PRIMARY KEY,pending INTEGER);
          CREATE TABLE IF NOT EXISTS model_runs(conversation TEXT PRIMARY KEY,owner TEXT,pid INTEGER,start TEXT,created REAL);
        """)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def settings(self, changes=None):
        with self.db() as db:
            if changes:
                for key, value in changes.items():
                    bounds = dict(
                        max_models=(1, 8),
                        wake_interval_ms=(2000, 60000),
                        run_timeout_seconds=(10, 3600),
                    )
                    if (
                        key not in bounds
                        or type(value) is not int
                        or not bounds[key][0] <= value <= bounds[key][1]
                    ):
                        raise ValueError("Invalid scheduler setting")
                    db.execute(
                        "INSERT OR REPLACE INTO settings VALUES (?,?)",
                        (key, json.dumps(value)),
                    )
            return dict(
                DEFAULTS,
                **{
                    r["key"]: json.loads(r["value"])
                    for r in db.execute("SELECT * FROM settings")
                },
            )

    def create(
        self,
        conversation,
        runtime,
        pane,
        goal,
        *,
        kind="schedule",
        schedule=None,
        next_run=None,
        watch_id=None,
        mode="auto",
    ):
        if not isinstance(goal, str) or not 1 <= len(goal) <= 4000 or not goal.strip():
            raise ValueError("task goal must be 1–4000 characters")
        if mode not in ("auto", "manual"):
            raise ValueError("mode must be auto or manual")
        identity = "task_" + secrets.token_hex(12)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT count(*) FROM tasks WHERE state NOT IN ('cancelled','succeeded','failed')"
                ).fetchone()[0]
                >= 128
            ):
                raise ValueError("At most 128 active tasks per service")
            db.execute(
                "INSERT INTO tasks(id,conversation,runtime,pane,server_pid,session_id,goal,kind,schedule,next_run,state,mode,watch_id,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    conversation,
                    runtime,
                    pane["pane_id"],
                    str(pane["pid"]),
                    pane["session_id"],
                    goal,
                    kind,
                    json.dumps(schedule),
                    next_run,
                    "waiting" if kind != "control" else "running",
                    mode,
                    watch_id,
                    time.time(),
                ),
            )
        return self.get(identity)

    @staticmethod
    def decode(row):
        if row is None:
            raise ValueError("Unknown task")
        row = dict(row)
        for key in ("schedule", "pending", "result"):
            row[key] = json.loads(row[key]) if row[key] else None
        return row

    def list(self):
        with self.db() as db:
            return [
                self.decode(r)
                for r in db.execute(
                    "SELECT * FROM tasks ORDER BY state IN ('cancelled','succeeded','failed'), updated DESC LIMIT 256"
                )
            ]

    def get(self, identity):
        with self.db() as db:
            return self.decode(
                db.execute("SELECT * FROM tasks WHERE id=?", (identity,)).fetchone()
            )

    def delete(self, identity):
        with self.db() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise ValueError("Unknown task")
            if row["state"] not in ("cancelled", "succeeded", "failed"):
                raise ValueError("Only ended tasks can be deleted")
            db.execute("DELETE FROM runs WHERE task=?", (identity,))
            db.execute("DELETE FROM tasks WHERE id=?", (identity,))
        return dict(id=identity, deleted=True)

    def purge_controls(self):
        """Remove legacy control-task rows; control leases are not tasks."""
        with self.db() as db:
            db.execute(
                "DELETE FROM runs WHERE task IN (SELECT id FROM tasks WHERE kind='control')"
            )
            deleted = db.execute("DELETE FROM tasks WHERE kind='control'").rowcount
        return deleted

    def change(self, identity, **values):
        allowed = {
            "runtime",
            "next_run",
            "state",
            "mode",
            "pending",
            "run_id",
            "last_wake",
            "result",
            "schedule",
            "watch_id",
        }
        if not values or set(values) - allowed:
            raise ValueError("Invalid task update")
        with self.db() as db:
            assignments, params = [], []
            for key, value in values.items():
                assignments.append(key + "=?")
                params.append(
                    json.dumps(value)
                    if key in ("pending", "result", "schedule") and value is not None
                    else value
                )
            db.execute(
                "UPDATE tasks SET "
                + ",".join(assignments)
                + ",revision=revision+1,updated=? WHERE id=?",
                (*params, time.time(), identity),
            )
        return self.get(identity)

    def pause(self, conversation, reason="manual"):
        with self.db() as db:
            db.execute(
                "DELETE FROM conversation_chats WHERE conversation=?", (conversation,)
            )
            db.execute(
                "INSERT OR REPLACE INTO conversation_pauses VALUES (?,?)",
                (conversation, reason),
            )
            db.execute(
                "UPDATE runs SET state='interrupted',finished=? WHERE id IN (SELECT run_id FROM tasks WHERE conversation=? AND run_id IS NOT NULL)",
                (time.time(), conversation),
            )
            db.execute(
                "UPDATE tasks SET state='paused',run_id=NULL,revision=revision+1,updated=? WHERE conversation=? AND state NOT IN ('cancelled','succeeded','failed')",
                (time.time(), conversation),
            )

    def resume(self, conversation):
        with self.db() as db:
            db.execute(
                "DELETE FROM conversation_pauses WHERE conversation=?", (conversation,)
            )
            db.execute(
                "UPDATE tasks SET state='waiting',pending=?,revision=revision+1,updated=? WHERE conversation=? AND state='paused'",
                (
                    json.dumps(dict(type="user_resume", force=True)),
                    time.time(),
                    conversation,
                ),
            )

    def paused(self, conversation):
        with self.db() as db:
            return (
                db.execute(
                    "SELECT reason FROM conversation_pauses WHERE conversation=?",
                    (conversation,),
                ).fetchone()
                is not None
            )

    def claim(self, identity, revision, event):
        now, run = time.time(), secrets.token_hex(16)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (identity,)).fetchone()
            if (
                not row
                or row["revision"] != revision
                or row["state"] in ("paused", "cancelled", "succeeded", "failed")
            ):
                return None
            if db.execute(
                "SELECT 1 FROM conversation_pauses WHERE conversation=?",
                (row["conversation"],),
            ).fetchone():
                return None
            if db.execute(
                "SELECT 1 FROM tasks WHERE conversation=? AND run_id IS NOT NULL AND id!=? AND state IN ('running','needs_input')",
                (row["conversation"], identity),
            ).fetchone():
                return None
            db.execute(
                "UPDATE tasks SET state='running',run_id=?,pending=NULL,last_wake=?,updated=? WHERE id=?",
                (run, now, now, identity),
            )
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                (run, identity, "dispatching", json.dumps(event), now, None, None),
            )
        return run

    def run(self, identity):
        with self.db() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (identity,)).fetchone()
            return dict(row) if row else None

    def run_update(self, identity, state, detail=None):
        with self.db() as db:
            db.execute(
                "UPDATE runs SET state=?,detail=?,finished=? WHERE id=?"
                + (" AND state='dispatching'" if state == "submitted" else ""),
                (
                    state,
                    json.dumps(detail) if detail else None,
                    None if state == "submitted" else time.time(),
                    identity,
                ),
            )

    def history(self, identity):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM runs WHERE task=? ORDER BY started DESC LIMIT 32",
                    (identity,),
                )
            ]

    def finish(self, identity, conversation, outcome, summary):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.decode(
                db.execute("SELECT * FROM tasks WHERE id=?", (identity,)).fetchone()
            )
            if row["conversation"] != conversation:
                raise PermissionError("Task belongs to a different conversation")
            if (
                row["state"] in ("cancelled", "paused")
                or db.execute(
                    "SELECT 1 FROM conversation_pauses WHERE conversation=?",
                    (conversation,),
                ).fetchone()
            ):
                raise ValueError(
                    "A cancelled/paused task cannot be completed by the Agent"
                )
            result = dict(
                outcome=outcome,
                summary=summary,
                source="agent",
                task_complete=outcome == "succeeded",
            )
            if row["run_id"]:
                db.execute(
                    "UPDATE runs SET state=?,detail=?,finished=? WHERE id=?",
                    (outcome, json.dumps(result), time.time(), row["run_id"]),
                )
            state = (
                "waiting"
                if row["next_run"] is not None and outcome == "succeeded"
                else outcome
            )
            db.execute(
                "UPDATE tasks SET state=?,run_id=NULL,result=?,revision=revision+1,updated=? WHERE id=?",
                (state, json.dumps(result), time.time(), identity),
            )
        return self.get(identity)

    def resume_selected(self, identity, conversation, revision):
        """Resume only the confirmed task; never queue a second model turn."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (identity,)).fetchone()
            if (
                not row
                or row["conversation"] != conversation
                or row["revision"] != revision
                or row["state"] != "paused"
            ):
                raise ValueError("Task changed; request a fresh resume confirmation")
            db.execute(
                "DELETE FROM conversation_pauses WHERE conversation=?", (conversation,)
            )
            db.execute(
                "UPDATE tasks SET state='running',pending=NULL,run_id=NULL,result=NULL,revision=revision+1,updated=? WHERE id=?",
                (time.time(), identity),
            )
