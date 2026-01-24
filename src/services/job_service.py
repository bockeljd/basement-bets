
import os
import json
import traceback
from datetime import datetime
from contextlib import contextmanager
from src.database import get_db_connection, try_advisory_lock, release_advisory_lock, _exec

class JobContext:
    def __init__(self, job_name: str):
        self.job_name = job_name
        self.run_id = None
        self.conn = None
        self.state = {}
        
    def __enter__(self):
        """
        1. Open connection
        2. Acquire Lock
        3. Create 'running' entry in job_runs
        4. Load state
        """
        self.conn = get_db_connection().__enter__() # Manually enter context
        
        # 1. Lock
        if not try_advisory_lock(self.conn, f"job_lock:{self.job_name}"):
            # Failed to lock
            self.conn.close() 
            raise JobLockedException(f"Job {self.job_name} is currently running.")
            
        # 2. Log Start
        try:
            cur = _exec(self.conn, 
                "INSERT INTO job_runs (job_name, status) VALUES (:n, 'running') RETURNING id",
                {"n": self.job_name}
            )
            self.run_id = cur.fetchone()[0]
            self.conn.commit()
        except Exception as e:
            print(f"[Job] Failed to log start: {e}")
            
        # 3. Load State
        try:
            cur = _exec(self.conn, "SELECT state FROM job_state WHERE job_name = :n", {"n": self.job_name})
            row = cur.fetchone()
            if row and row['state']:
                # row['state'] is likely already dict if using DictCursor and JSONB?
                # psycopg2 handles JSONB transparently usually
                self.state = row['state'] if isinstance(row['state'], dict) else json.loads(row['state'])
        except Exception as e:
            print(f"[Job] Failed to load state: {e}")
            self.state = {}
            
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        1. Update job_runs status
        2. Save state
        3. Release Lock
        4. Close connection
        """
        status = 'success'
        error_msg = None
        
        if exc_type:
            if exc_type == JobLockedException:
                # This shouldn't happen deep inside usually, but if manually raised
                status = 'skipped'
            else:
                status = 'failure'
                error_msg = str(exc_val)
        
        if self.conn and not self.conn.closed:
            try:
                # Update State
                if self.state:
                    state_json = json.dumps(self.state)
                    q = """
                    INSERT INTO job_state (job_name, state, updated_at) VALUES (:n, :s, NOW())
                    ON CONFLICT(job_name) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()
                    """
                    _exec(self.conn, q, {"n": self.job_name, "s": state_json})
                
                # Update Run Log
                if self.run_id:
                    q_run = """
                    UPDATE job_runs 
                    SET status = :s, finished_at = NOW(), error = :e 
                    WHERE id = :id
                    """
                    _exec(self.conn, q_run, {"s": status, "e": error_msg, "id": self.run_id})
                
                self.conn.commit()
                
                # Release Lock
                release_advisory_lock(self.conn, f"job_lock:{self.job_name}")
                
            except Exception as e:
                print(f"[Job] Exit handler failed: {e}")
            finally:
                self.conn.close()

class JobLockedException(Exception):
    pass
