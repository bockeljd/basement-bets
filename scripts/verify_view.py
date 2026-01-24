
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_db_connection, _exec

def check_view():
    print("Checking for latest_odds_snapshots view...")
    query = "SELECT count(*) FROM latest_odds_snapshots"
    try:
        with get_db_connection() as conn:
            cur = _exec(conn, query)
            count = cur.fetchone()[0]
            print(f"[Pass] View exists. Rows: {count}")
    except Exception as e:
        print(f"[Fail] View check failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_view()
