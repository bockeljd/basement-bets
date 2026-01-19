import sys
import os

sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec

def main():
    print("Checking status values in database...\n")
    
    with get_db_connection() as conn:
        # Check all distinct status values
        cursor = _exec(conn, """
            SELECT status, COUNT(*) as count
            FROM bets
            GROUP BY status
            ORDER BY count DESC
        """)
        
        print("Status Distribution:")
        for row in cursor.fetchall():
            print(f"  '{row['status']}': {row['count']} bets")
            
        print("\n" + "="*50)
        
        # Check for 'Won' vs 'WON' vs other variations
        cursor = _exec(conn, """
            SELECT COUNT(*) as won_count
            FROM bets
            WHERE UPPER(status) = 'WON'
        """)
        won_count = cursor.fetchone()['won_count']
        print(f"\nBets with status='Won' (case-insensitive): {won_count}")
        
        # Sample some Won bets
        cursor = _exec(conn, """
            SELECT id, bet_type, selection, status, profit
            FROM bets
            WHERE UPPER(status) = 'WON'
            LIMIT 5
        """)
        
        print("\nSample Won Bets:")
        for row in cursor.fetchall():
            print(f"  ID {row['id']}: {row['bet_type']} | Status: '{row['status']}' | Profit: ${row['profit']}")

if __name__ == "__main__":
    main()
