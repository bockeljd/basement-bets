import sys
import os

sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec

def main():
    print("DEBUGGING STATUS VALUES...")
    
    with get_db_connection() as conn:
        cursor = _exec(conn, "SELECT id, status FROM bets WHERE UPPER(status) LIKE '%WON%'")
        rows = cursor.fetchall()
        
        print(f"Found {len(rows)} potentially winning bets.")
        
        for row in rows[:10]:
            s = row['status']
            print(f"ID {row['id']}: '{s}' (len={len(s)}) - Hex: {s.encode('utf-8').hex()}")
            
        # Check non-winning statuses too
        cursor = _exec(conn, "SELECT DISTINCT status FROM bets")
        print("\nAll Distinct Statuses:")
        for row in cursor.fetchall():
            s = row['status']
            print(f"  '{s}' (len={len(s)})")

if __name__ == "__main__":
    main()
