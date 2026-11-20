import json
import sys

from src.database import _exec, get_db_connection


class JobLockedException(Exception):
    pass


class JobContext:
    """Hold a transaction lock for the job, independent of audit-log commits."""

    def __init__(self, job_name):
        self.job_name = job_name
        self.state = {}
        self.run_id = None

    def __enter__(self):
        self._lock_context = get_db_connection(dedicated=True)
        lock_conn = self._lock_context.__enter__()
        try:
            acquired = _exec(lock_conn, "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                             (f"job_lock:{self.job_name}",)).fetchone()[0]
            with get_db_connection() as conn:
                if acquired:
                    self.run_id = _exec(conn, """INSERT INTO job_runs(job_name,status)
                        VALUES (%s,'running') RETURNING id""", (self.job_name,)).fetchone()[0]
                    row = _exec(conn, "SELECT state FROM job_state WHERE job_name=%s",
                                (self.job_name,)).fetchone()
                    if row and row[0]:
                        self.state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                else:
                    _exec(conn, """INSERT INTO job_runs(job_name,status,finished_at)
                        VALUES (%s,'skipped',NOW())""", (self.job_name,))
                conn.commit()
            if not acquired:
                raise JobLockedException(f"Job {self.job_name} is currently running")
            return self
        except BaseException:
            self._lock_context.__exit__(*sys.exc_info())
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            with get_db_connection() as conn:
                detail = json.dumps(self.state)
                if exc_type is None and self.state:
                    _exec(conn, """INSERT INTO job_state(job_name,state,updated_at)
                        VALUES (%s,%s,NOW()) ON CONFLICT(job_name) DO UPDATE
                        SET state=EXCLUDED.state, updated_at=NOW()""", (self.job_name, detail))
                _exec(conn, """UPDATE job_runs SET status=%s,finished_at=NOW(),error=%s,detail=%s
                    WHERE id=%s""", ('failure' if exc_type else 'success',
                                     str(exc_value) if exc_type else None, detail, self.run_id))
                conn.commit()
        finally:
            self._lock_context.__exit__(None, None, None)
