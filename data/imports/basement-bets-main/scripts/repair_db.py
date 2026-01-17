import sys
import os
import sqlite3

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.database import get_db_connection, _exec

def repair_database():
    print("--- REPAIRING DATABASE ---")
    
    with get_db_connection() as conn:
        # 1. Count Invalid Rows
        # conn.row_factory = sqlite3.Row # Removed for PG compatibility
        c = conn.cursor()
        
        # Check for NULL teams
        c.execute("SELECT count(*) FROM model_predictions WHERE home_team IS NULL OR away_team IS NULL")
        invalid_count = c.fetchone()[0]
        print(f"Found {invalid_count} predictions with missing Team Names (NULL).")
        
        # Check for Stale Pending (older than Yesterday)
        # Using simple string comparison for ISO dates
        stale_date = '2026-01-14' 
        c.execute(f"SELECT count(*) FROM model_predictions WHERE result='Pending' AND date < '{stale_date}'")
        stale_count = c.fetchone()[0]
        print(f"Found {stale_count} stale pending predictions (older than {stale_date}).")
        
        # 2. DELETE INVALID
        if invalid_count > 0:
            print("Deleting predictions with missing teams...")
            _exec(conn, "DELETE FROM model_predictions WHERE home_team IS NULL OR away_team IS NULL")
            conn.commit()
            print("Deleted.")

        # 3. DELETE STALE (Optional, but good for cleanup if they are stuck)
        if stale_count > 0:
             print("Deleting stale pending predictions...")
             _exec(conn, f"DELETE FROM model_predictions WHERE result='Pending' AND date < '{stale_date}'")
             conn.commit()
             print("Deleted.")
             
        # 4. Verify
        c.execute("SELECT count(*) FROM model_predictions")
        final_count = c.fetchone()[0]
        print(f"Final Prediction Count: {final_count}")

if __name__ == "__main__":
    repair_database()
