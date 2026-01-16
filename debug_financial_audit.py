import sys
import os

# Ensure src is in path
sys.path.append(os.path.abspath("."))

from src.database import get_db_connection

def audit_financials():
    print("\n--- Auditing Financial Transactions ---")
    query = "SELECT * FROM transactions ORDER BY date DESC"
    
    deposits = []
    withdrawals = []
    others = []
    
    with get_db_connection() as conn:
        try:
           # conn.row_factory = None # Not needed for PG
           cur = conn.cursor()
           cur.execute(query)
           
           # Get column names
           cols = [desc[0] for desc in cur.description]
           
           rows = cur.fetchall()
           
           for r in rows:
               # Convert to dict
               d = dict(zip(cols, r))
               
               amt = d['amount']
               desc = d.get('description', '')
               typ = d['type']
               
               if typ == 'Deposit':
                   deposits.append(d)
               elif typ == 'Withdrawal':
                   withdrawals.append(d)
               else:
                   others.append(d)
                   
        except Exception as e:
            print(f"Error: {e}")
            return

    print(f"Total Deposits Found: {len(deposits)}")
    tot_dep = sum(d['amount'] for d in deposits)
    print(f"Total Deposit Amount: ${tot_dep:,.2f}")
    
    print("-" * 20)
    print(f"Top 5 Deposits:")
    for d in deposits[:5]:
        print(f"  {d['date']} | {d['provider']} | {d['amount']} | {d['description']}")

    print("-" * 20)
    print(f"Total Withdrawals Found: {len(withdrawals)}")
    tot_wd = sum(abs(d['amount']) for d in withdrawals)
    print(f"Total Withdrawal Amount: ${tot_wd:,.2f}")
    
    # Hypothesis: User might be filtering out 'Other' or specific dates?
    # Or maybe 'Manual Import' ($100, $20) + ($100 deposit)? 
    # $220 diff in deposits.
    # $200 diff in withdrawals.
    
    # Try excluding 'Manual Import' or 'Other'?
    dep_clean = [d for d in deposits if 'Manual' not in d.get('description', '')]
    wd_clean = [d for d in withdrawals if 'Manual' not in d.get('description', '')]
    
    print(f"  (Excluding 'Manual'): D: ${sum(d['amount'] for d in dep_clean):,.2f} | W: ${sum(abs(d['amount']) for d in wd_clean):,.2f}")
    
    # Try excluding specific providers or amounts?
    # Look for transactions of exactly $200 or $220?
    # Or combinations.
    
    print("-" * 20)
    print(f"Top 5 Withdrawals:")
    for d in withdrawals[:5]:
        print(f"  {d['date']} | {d['provider']} | {d['amount']} | {d['description']}")

    print("=" * 30)
    print(f"Realized Profit (W - D): ${tot_wd - tot_dep:,.2f}")
    
    # Check for perfect duplicates (Same date, amount, provider)
    print("\n[Audit] Checking for potential duplicates...")
    seen = {}
    dupes = []
    for d in deposits + withdrawals:
        # Fingerprint: Date + Amount + Provider
        fp = f"{d['date']}_{d['amount']}_{d['provider']}"
        if fp in seen:
            dupes.append(d)
        seen[fp] = True
        
    if dupes:
        print(f"Found {len(dupes)} items with same Date/Amount/Provider (Review carefully):")
        for d in dupes[:10]:
             print(f"  {d['type']} | {d['date']} | {d['amount']} | {d['provider']}")
    else:
        print("No obvious duplicates based on Date+Amount+Provider.")

if __name__ == "__main__":
    audit_financials()
