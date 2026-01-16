import sys
import os

# Add root to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.database import get_db_connection, _exec

def delete_deposit():
    print("Deleting $1900 deposit...")
    # Criteria: Amount 1900, DraftKings, Deposit
    # Using range 1899-1901 just in case of float weirdness, though exact match should work for 1900.0
    query_check = "SELECT * FROM transactions WHERE amount = 1900 AND provider = 'DraftKings' AND type = 'Deposit'"
    
    with get_db_connection() as conn:
        # Check first
        cursor = _exec(conn, query_check)
        rows = cursor.fetchall()
        print(f"Found {len(rows)} matching transactions.")
        for r in rows:
            print(f" - Deleting: {r['date']} - {r['description']} - ${r['amount']}")
            
        if len(rows) == 0:
            print("No matching transaction found.")
            return

        # Delete
        query_delete = "DELETE FROM transactions WHERE amount = 1900 AND provider = 'DraftKings' AND type = 'Deposit'"
        _exec(conn, query_delete)
        conn.commit()
        print("Deletion committed.")

if __name__ == "__main__":
    delete_deposit()
