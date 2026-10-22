from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from ..timeutil import iso, now_london

PRUNE_AFTER = timedelta(days=7)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    assignee TEXT NOT NULL,
    due TEXT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    done_at REAL NULL
)
"""


class TaskStore:
    """SQLite-backed tasks. Calls are tiny; one connection guarded by a lock."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        # Create the file 0600 before sqlite opens it.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute(_SCHEMA)

    @staticmethod
    def _task(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "title": row["title"], "assignee": row["assignee"],
            "due": row["due"], "done": bool(row["done"]),
        }

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM tasks ORDER BY created_at, rowid").fetchall()

        def key(r: sqlite3.Row):
            # Parse due so mixed GMT/BST offsets sort correctly; sort is stable (created order).
            due = datetime.fromisoformat(r["due"]).timestamp() if r["due"] else float("inf")
            return (bool(r["done"]), due)

        return [self._task(r) for r in sorted(rows, key=key)]

    def add(self, title: str, assignee: str, due: str | None) -> dict:
        tid = uuid.uuid4().hex[:12]
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO tasks (id, title, assignee, due, done, created_at)"
                " VALUES (?, ?, ?, ?, 0, ?)",
                (tid, title, assignee, due, now_london().timestamp()),
            )
        return {"id": tid, "title": title, "assignee": assignee, "due": due, "done": False}

    def set_done(self, task_id: str, done: bool, now: datetime | None = None) -> bool:
        stamp = (now or now_london()).timestamp() if done else None
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE tasks SET done = ?, done_at = ? WHERE id = ?", (int(done), stamp, task_id)
            )
        return cur.rowcount > 0

    def delete(self, task_id: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0

    def prune(self, now: datetime) -> int:
        cutoff = (now - PRUNE_AFTER).timestamp()
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM tasks WHERE done = 1 AND done_at IS NOT NULL AND done_at < ?",
                (cutoff,),
            )
        return cur.rowcount


class TasksProvider:
    """Hub provider: prune expired done tasks, then publish the list."""

    def __init__(self, store: TaskStore):
        self.store = store

    async def refresh(self, now: datetime) -> list[dict]:
        def work() -> list[dict]:
            self.store.prune(now)
            return self.store.list()

        return await asyncio.to_thread(work)


def normalise_due(value: object) -> str | None:
    """Validate a client `due` and return it as a London-offset ISO string.

    Raises ValueError for anything that is not null or an ISO string with an offset.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("due must be an ISO string or null") from None
    if dt.tzinfo is None:
        raise ValueError("due must include a UTC offset")
    return iso(dt)
