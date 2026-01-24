
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_admin_db_connection, init_snapshots_db

def fix_schema():
    print("[Fix] Recreating odds_snapshots with correct schema...")
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS odds_snapshots CASCADE;")
        conn.commit()
    
    # Re-init
    init_snapshots_db()
    print("[Fix] Done.")

if __name__ == "__main__":
    fix_schema()
