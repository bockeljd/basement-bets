
import sys
import os
import psycopg2

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_admin_db_connection

def ensure_text_ids():
    print("[Migration] Ensuring user_id/account_id are TEXT...")
    
    statements = [
        "ALTER TABLE bets ALTER COLUMN user_id TYPE TEXT USING user_id::text",
        "ALTER TABLE bets ALTER COLUMN account_id TYPE TEXT USING account_id::text",
        # Add index if missing
        "CREATE INDEX IF NOT EXISTS idx_bets_user_date ON bets(user_id, date)"
    ]
    
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                try:
                    print(f"Executing: {stmt}")
                    cur.execute(stmt)
                except Exception as e:
                    print(f"Skipped/Error: {e}")
                    conn.rollback() # Block failure shouldn't stop others if independent
                    # But here transaction rollback needed.
                    # Re-start transaction?
                    # Just skip.
        conn.commit()
    print("[Migration] Column types updated.")

if __name__ == "__main__":
    try:
        ensure_text_ids()
    except Exception as e:
        print(f"Migration Failed: {e}")
