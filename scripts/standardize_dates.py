
import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

from src.database import get_db_connection
from datetime import datetime
from dateutil.parser import parse as parse_date

def standardize_dates():
    print("--- Standardizing Dates ---")
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # 1. Fetch all bets
        cur.execute("SELECT id, date FROM bets")
        bets = cur.fetchall()
        
        updates = []
        for b in bets:
            raw = b['date']
            try:
                # Parse robustly
                dt = parse_date(raw)
                clean_date = dt.strftime("%Y-%m-%d")
                
                if clean_date != raw:
                    updates.append((clean_date, b['id']))
            except:
                print(f"Skipping invalid date: {raw} (ID: {b['id']})")
                
        # 2. Bulk Update
        print(f"Updating {len(updates)} records...")
        success_count = 0
        from psycopg2 import IntegrityError
        
        for new_date, bid in updates:
            try:
                cur.execute("UPDATE bets SET date = %s WHERE id = %s", (new_date, bid))
                success_count += 1
            except IntegrityError:
                conn.rollback()
                print(f"[SKIP] ID {bid}: Update to {new_date} would create duplicate.")
            except Exception as e:
                conn.rollback()
                print(f"[ERROR] ID {bid}: {e}")
            else:
                conn.commit()
                
        print(f"Done. Updated {success_count}/{len(updates)} records.")

if __name__ == "__main__":
    standardize_dates()
