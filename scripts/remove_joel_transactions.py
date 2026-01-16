import sys
import os
import sqlite3

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.database import get_db_connection, _exec

def remove_joel():
    print("--- REMOVING 'JOEL' TRANSACTIONS ---")
    
    with get_db_connection() as conn:
         # conn.row_factory = sqlite3.Row # PG compat
         c = conn.cursor()
         
         # 1. Count them first
         query_check = "SELECT count(*), sum(amount) FROM transactions WHERE description LIKE '%Joel%'"
         c.execute(query_check)
         cnt, total_amt = c.fetchone()
         
         print(f"Found {cnt} transactions for 'Joel' totaling ${total_amt or 0}.")
         
         if cnt > 0:
             print("Deleting...")
             _exec(conn, "DELETE FROM transactions WHERE description LIKE '%Joel%'")
             conn.commit()
             print("Deletion complete.")
         else:
             print("No 'Joel' transactions found.")

if __name__ == "__main__":
    remove_joel()
