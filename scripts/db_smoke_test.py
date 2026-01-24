
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.database import get_db_connection, _exec
from src.config import settings

def smoke_test():
    print("--- Postgres Smoke Test ---")
    if not settings.DATABASE_URL:
        print("[FAIL] DATABASE_URL not set.")
        sys.exit(1)
        
    print(f"[Info] Environment: {settings.APP_ENV}")
    print(f"[Info] Reset Mode: {os.environ.get('BASEMENT_DB_RESET', '0')}")
    
    try:
        with get_db_connection() as conn:
            # 1. Simple Select
            cur = _exec(conn, "SELECT 1")
            val = cur.fetchone()[0]
            print(f"[Pass] SELECT 1 returned: {val}")
            
            # 2. Check Tables
            tables = ["events", "odds_snapshots", "model_predictions", "game_results"]
            for t in tables:
                try:
                    cur = _exec(conn, f"SELECT COUNT(*) FROM {t}")
                    count = cur.fetchone()[0]
                    print(f"[Pass] Table '{t}' exists. Rows: {count}")
                except Exception as e:
                    print(f"[FAIL] Table '{t}' check failed: {e}")
                    conn.rollback() 
            
    except Exception as e:
        print(f"[FAIL] Connection failed: {e}")
        sys.exit(1)
        
    print("[Success] All smoke tests passed.")

if __name__ == "__main__":
    smoke_test()
