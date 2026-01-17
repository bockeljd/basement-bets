import sys
import os
import sqlite3

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.database import get_db_connection

def audit_deposits():
    print("--- DETAILED DEPOSIT AUDIT ---")
    
    with get_db_connection() as conn:
         # conn.row_factory = sqlite3.Row # PG compat
         c = conn.cursor()
         
         # 1. Fetch ALL Deposits
         query = "SELECT date, provider, amount, description, type FROM transactions WHERE type='Deposit' ORDER BY date DESC"
         c.execute(query)
         rows = c.fetchall()
         
         total = 0.0
         print(f"{'Date':<20} | {'Provider':<15} | {'Amount':>10} | {'Description'}")
         print("-" * 80)
         
         for r in rows:
             # handle dict-like or tuple-like depending on driver
             try:
                 date = r['date']
                 prov = r['provider']
                 amt = r['amount']
                 desc = r['description']
             except:
                 date = r[0]
                 prov = r[1]
                 amt = r[2]
                 desc = r[3]
                 
             total += amt
             print(f"{date:<20} | {prov:<15} | {amt:>10.2f} | {desc}")
             
         print("-" * 80)
         print(f"TOTAL DEPOSITS: ${total:,.2f}")
         
         # 2. Check overlap with 'Other' (Transfers) to ensure we aren't missing any implicit ones
         # Use heuristic: is there any 'Other' with positive amount that looks like a deposit?
         print("\n--- CHECKING 'OTHER' (POSITIVE) ---")
         c.execute("SELECT date, provider, amount, description FROM transactions WHERE type='Other' AND amount > 0")
         other_rows = c.fetchall()
         for r in other_rows:
             try:
                 date = r['date']
                 prov = r['provider']
                 amt = r['amount']
                 desc = r['description']
             except:
                 date = r[0]
                 prov = r[1]
                 amt = r[2]
                 desc = r[3]
             print(f"{date:<20} | {prov:<15} | {amt:>10.2f} | {desc}")

if __name__ == "__main__":
    audit_deposits()
