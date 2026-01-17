import sys
import os
import sqlite3

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.database import get_db_connection, _exec

def fix_duplicate():
    print("--- FIXING DUPLICATE TRANSACTION ---")
    query = """
        SELECT txn_id, date, type, amount 
        FROM transactions 
        WHERE date LIKE '2023-03-17%' AND type='Withdrawal' AND abs(amount) = 100.0
    """
    
    with get_db_connection() as conn:
         # conn.row_factory = sqlite3.Row # PG compat
         c = conn.cursor()
         c.execute(query)
         rows = c.fetchall()
         
         if len(rows) > 1:
             print(f"Found {len(rows)} duplicates. Keeping one, deleting the rest.")
             # Keep the first one
             keep_id = rows[0]['txn_id'] # PG uses dict-like rows usually
             
             for i in range(1, len(rows)):
                 del_id = rows[i]['txn_id']
                 print(f"Deleting duplicate ID: {del_id}")
                 _exec(conn, "DELETE FROM transactions WHERE txn_id = %s", (del_id,))
             
             conn.commit()
             print("Deduplication complete.")
         else:
             print("No duplicates found to delete.")

if __name__ == "__main__":
    fix_duplicate()
