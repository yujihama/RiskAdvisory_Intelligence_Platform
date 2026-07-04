from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JOB_STATUSES: tuple[str, ...] = ("submitted", "working", "completed", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    request_payload TEXT NOT NULL,
    result_summary TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    job_id: str
    job_type: str
    status: str
    trace_id: str
    request_payload: dict[str, Any]
    result_summary: dict[str, Any] | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JobRecord":
        return cls(
            job_id=row["job_id"],
            job_type=row["job_type"],
            status=row["status"],
            trace_id=row["trace_id"],
            request_payload=json.loads(row["request_payload"]),
            result_summary=json.loads(row["result_summary"]) if row["result_summary"] else None,
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


class JobStore:
    """SQLite-backed job state store. A single file, no ORM, safe for a small ThreadPoolExecutor worker pool."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    def create_job(self, job_id: str, job_type: str, trace_id: str, request_payload: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, job_type, status, trace_id, request_payload, created_at) "
                "VALUES (?, ?, 'submitted', ?, ?, ?)",
                (job_id, job_type, trace_id, json.dumps(request_payload, ensure_ascii=False, default=str), _now_iso()),
            )
            self._conn.commit()

    def mark_working(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status='working', started_at=? WHERE job_id=?",
                (_now_iso(), job_id),
            )
            self._conn.commit()

    def mark_completed(self, job_id: str, result_summary: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status='completed', finished_at=?, result_summary=? WHERE job_id=?",
                (_now_iso(), json.dumps(result_summary, ensure_ascii=False, default=str), job_id),
            )
            self._conn.commit()

    def mark_failed(self, job_id: str, error_message: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status='failed', finished_at=?, error_message=? WHERE job_id=?",
                (_now_iso(), error_message, job_id),
            )
            self._conn.commit()

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return JobRecord.from_row(row) if row else None

    def list_jobs(self, status: str | None = None) -> list[JobRecord]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC", (status,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [JobRecord.from_row(row) for row in rows]

    def recover_orphans(self) -> int:
        """Mark any job left in submitted/working from a previous process as failed:orphaned_by_restart."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id FROM jobs WHERE status IN ('submitted', 'working')"
            ).fetchall()
            orphan_ids = [row["job_id"] for row in rows]
            if orphan_ids:
                now = _now_iso()
                self._conn.executemany(
                    "UPDATE jobs SET status='failed', finished_at=?, error_message='orphaned_by_restart' WHERE job_id=?",
                    [(now, job_id) for job_id in orphan_ids],
                )
                self._conn.commit()
        return len(orphan_ids)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
