
import sys
import os
sys.path.append(os.getcwd())

from src.database import get_db_connection

def migrate():
    print("--- Adding validation_errors column ---")
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE bets ADD COLUMN validation_errors TEXT")
            print("Column added successfully.")
            conn.commit()
        except Exception as e:
            print(f"Migration skipped/failed: {e}")

if __name__ == "__main__":
    migrate()
