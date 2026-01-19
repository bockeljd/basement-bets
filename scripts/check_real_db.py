
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.database import get_db_connection, _exec

def main():
    print("Checking REAL DB Content...")
    try:
        with get_db_connection() as conn:
            # Check DB Type
            is_pg = hasattr(conn, 'cursor_factory')
            print(f"Connected to: {'Postgres' if is_pg else 'SQLite'}")
            
            # Check Transactions
            cur = _exec(conn, "SELECT COUNT(*) as c FROM transactions")
            txn_count = cur.fetchone()['c'] # psycopg2 dict cursor or sqlite row
            
            # Check Bets
            cur = _exec(conn, "SELECT COUNT(*) as c FROM bets")
            bet_count = cur.fetchone()['c']
            
            print(f"Transactions Count: {txn_count}")
            print(f"Bets Count: {bet_count}")
            
            if bet_count > 0:
                 cur = _exec(conn, "SELECT * FROM bets LIMIT 1")
                 row = cur.fetchone()
                 status = row.get('status')
                 print(f"Sample Bet Status: {status}")

            if txn_count > 0:
                 cur = _exec(conn, "SELECT * FROM transactions LIMIT 5")
                 rows = cur.fetchall()
                 for r in rows:
                     print(f"Txn: {r['provider']} {r['type']} {r['amount']}")
                     
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
