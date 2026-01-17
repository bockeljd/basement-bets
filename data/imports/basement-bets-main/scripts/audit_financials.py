import sys
import os
import sqlite3

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.database import get_db_connection

def audit_financials():
    print("--- AUDIT: FINANCIAL TRANSACTIONS ---")
    
    with get_db_connection() as conn:
        # conn.row_factory = sqlite3.Row # Removed for PG compatibility
        c = conn.cursor()
        
        # 1. Get Totals by Type
        print("\n[Summary by Type]")
        c.execute("SELECT type, count(*), sum(amount) FROM transactions GROUP BY type")
        rows = c.fetchall()
        for r in rows:
            print(f"Type: {r[0]:<15} Count: {r[1]:<5} Sum: {r[2]}")
            
        # 2. Get Detail of 'Other' to see if we are missing Transfers
        print("\n[Detail: 'Other' Type]")
        c.execute("SELECT date, description, amount FROM transactions WHERE type='Other'")
        rows = c.fetchall()
        for r in rows:
            print(f"{r['date']} | {r['amount']:>8} | {r['description']}")
            
        # 3. Check for Duplicates (same date, amount, description)
        print("\n[Potential Duplicates]")
        c.execute("""
            SELECT date, type, amount, description, count(*) as cnt 
            FROM transactions 
            GROUP BY date, type, amount, description 
            HAVING count(*) > 1
        """)
        dupes = c.fetchall()
        if dupes:
            for d in dupes:
                 print(f"DUPE (x{d['cnt']}): {d['date']} | {d['type']} | {d['amount']} | {d['description']}")
        else:
            print("No partial duplicates found.")

        # 4. Total Calculation Emulation
        print("\n[Recalculating Totals]")
        c.execute("SELECT type, amount, description FROM transactions")
        all_txns = c.fetchall()
        
        calc_deposit = 0.0
        calc_withdraw = 0.0
        
        for t in all_txns:
            typ = t['type']
            amt = t['amount']
            desc = t['description']
            
            if typ == 'Deposit':
                calc_deposit += amt
            elif typ == 'Withdrawal':
                calc_withdraw += abs(amt)
            elif typ == 'Other':
                # Check heuristic
                pass
                
        print(f"Calculated Deposits:    ${calc_deposit:,.2f}")
        print(f"Calculated Withdrawals: ${calc_withdraw:,.2f}")
        print(f"Calculated Net Profit:  ${calc_withdraw - calc_deposit:,.2f} (Withdrawn - Deposited)")

if __name__ == "__main__":
    audit_financials()
