from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any

from src.database import get_db_connection, get_admin_db_connection, _exec


DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_sync_jobs_table() -> None:
    """Create sync_jobs table if missing.

Serverless-safe: called on-demand from API/worker.
"""
    ddl = """
    CREATE TABLE IF NOT EXISTS sync_jobs (
      id BIGSERIAL PRIMARY KEY,
      user_id TEXT NOT NULL,
      provider TEXT NOT NULL,
      status TEXT NOT NULL,
      requested_at TIMESTAMPTZ NOT NULL,
      started_at TIMESTAMPTZ NULL,
      finished_at TIMESTAMPTZ NULL,
      worker_id TEXT NULL,
      error TEXT NULL,
      meta JSONB NULL
    );

    CREATE INDEX IF NOT EXISTS idx_sync_jobs_user_status_requested
      ON sync_jobs (user_id, status, requested_at DESC);

    CREATE INDEX IF NOT EXISTS idx_sync_jobs_status_requested
      ON sync_jobs (status, requested_at ASC);
    """
    with get_admin_db_connection() as conn:
        # psycopg2 doesn't allow multiple statements in one execute by default; split.
        for stmt in [s.strip() for s in ddl.split(';') if s.strip()]:
            _exec(conn, stmt)
        conn.commit()


def create_sync_job(provider: str, user_id: str = DEFAULT_USER_ID, meta: Optional[dict[str, Any]] = None) -> dict:
    ensure_sync_jobs_table()
    provider = (provider or "").strip()
    if provider not in ("draftkings", "fanduel"):
        raise ValueError("provider must be 'draftkings' or 'fanduel'")

    with get_db_connection() as conn:
        cur = _exec(
            conn,
            """
            INSERT INTO sync_jobs (user_id, provider, status, requested_at, meta)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, user_id, provider, status, requested_at;
            """,
            (user_id, provider, "QUEUED", _now_utc(), json.dumps(meta or {})),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return row


def claim_next_job(worker_id: str, provider: Optional[str] = None) -> Optional[dict]:
    """Atomically claim the next queued job."""
    ensure_sync_jobs_table()
    with get_db_connection() as conn:
        params = ["QUEUED"]
        prov_clause = ""
        if provider:
            prov_clause = " AND provider = %s "
            params.append(provider)

        # FOR UPDATE SKIP LOCKED prevents multiple workers claiming same row.
        cur = _exec(
            conn,
            f"""
            WITH next_job AS (
              SELECT id
              FROM sync_jobs
              WHERE status = %s
              {prov_clause}
              ORDER BY requested_at ASC
              LIMIT 1
              FOR UPDATE SKIP LOCKED
            )
            UPDATE sync_jobs
            SET status = 'RUNNING', started_at = %s, worker_id = %s
            WHERE id IN (SELECT id FROM next_job)
            RETURNING id, user_id, provider, status, requested_at, started_at, worker_id, meta;
            """,
            tuple(params + [_now_utc(), worker_id]),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def mark_job_needs_login(job_id: int, message: str = "Login required") -> None:
    with get_db_connection() as conn:
        _exec(
            conn,
            "UPDATE sync_jobs SET status='NEEDS_LOGIN', error=%s WHERE id=%s",
            (message, job_id),
        )
        conn.commit()


def mark_job_done(job_id: int, meta: Optional[dict[str, Any]] = None) -> None:
    with get_db_connection() as conn:
        _exec(
            conn,
            "UPDATE sync_jobs SET status='DONE', finished_at=%s, error=NULL, meta=%s WHERE id=%s",
            (_now_utc(), json.dumps(meta or {}), job_id),
        )
        conn.commit()


def mark_job_error(job_id: int, error: str) -> None:
    with get_db_connection() as conn:
        _exec(
            conn,
            "UPDATE sync_jobs SET status='ERROR', finished_at=%s, error=%s WHERE id=%s",
            (_now_utc(), error[:2000], job_id),
        )
        conn.commit()


def get_latest_jobs(user_id: str = DEFAULT_USER_ID, limit: int = 5) -> list[dict]:
    ensure_sync_jobs_table()
    with get_db_connection() as conn:
        cur = _exec(
            conn,
            """
            SELECT id, provider, status, requested_at, started_at, finished_at, worker_id, error, meta
            FROM sync_jobs
            WHERE user_id=%s
            ORDER BY requested_at DESC
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
