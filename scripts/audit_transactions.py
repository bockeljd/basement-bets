import sys
import os

sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec

def main():
    print("Auditing Transaction Totals...\n")
    
    # Expected targets from user
    targets = {
        'DraftKings': {'Deposit': 747.38, 'Withdrawal': 1035.38},
        'Barstool': {'Deposit': 58.36, 'Withdrawal': 89.76},
        'FanDuel': {'Deposit': 120.00, 'Withdrawal': 491.34},
        'Other': {'Deposit': 0.0, 'Withdrawal': 210.00}
    }
    
    with get_db_connection() as conn:
        # Get ALL transactions grouped by provider and type
        cursor = _exec(conn, """
            SELECT provider, type, description, amount
            FROM transactions
            WHERE type IN ('Deposit', 'Withdrawal')
            ORDER BY provider, type, description
        """)
        
        rows = cursor.fetchall()
        
        print(f"Total transaction records: {len(rows)}\n")
        print("="*80)
        
        # Manual aggregation to see what's happening
        from collections import defaultdict
        totals = defaultdict(lambda: {'Deposit': 0.0, 'Withdrawal': 0.0})
        
        for row in rows:
            prov = row['provider']
            typ = row['type']
            amt = float(row['amount'])
            desc = row['description'] or ''
            
            # Check if analytics.py would skip this
            skip_marker = ""
            if 'Manual' in desc:
                skip_marker = " [SKIPPED by analytics.py]"
            
            # For withdrawal, use absolute value (analytics does this)
            if typ == 'Withdrawal':
                totals[prov][typ] += abs(amt)
            else:
                totals[prov][typ] += amt
                
            print(f"{prov:15} | {typ:12} | ${amt:10.2f} | {desc[:40]}{skip_marker}")
        
        print("\n" + "="*80)
        print("\nAGGREGATED TOTALS (including all transactions):\n")
        
        for prov in sorted(totals.keys()):
            dep = totals[prov]['Deposit']
            wit = totals[prov]['Withdrawal']
            
            target_dep = targets.get(prov, {}).get('Deposit', 0)
            target_wit = targets.get(prov, {}).get('Withdrawal', 0)
            
            dep_match = "✓" if abs(dep - target_dep) < 0.01 else "✗"
            wit_match = "✓" if abs(wit - target_wit) < 0.01 else "✗"
            
            print(f"{prov:15} | Deposits: ${dep:8.2f} {dep_match} (target: ${target_dep:8.2f}) | Withdrawals: ${wit:8.2f} {wit_match} (target: ${target_wit:8.2f})")
        
        # Now check what analytics.py would return
        print("\n" + "="*80)
        print("\nWHAT ANALYTICS.PY RETURNS (filtering 'Manual' in description):\n")
        
        cursor = _exec(conn, """
            SELECT provider, type, SUM(ABS(amount)) as total
            FROM transactions
            WHERE type IN ('Deposit', 'Withdrawal')
              AND (description NOT LIKE '%Manual%' OR description IS NULL)
            GROUP BY provider, type
            ORDER BY provider, type
        """)
        
        analytics_totals = defaultdict(lambda: {'Deposit': 0.0, 'Withdrawal': 0.0})
        for row in cursor.fetchall():
            analytics_totals[row['provider']][row['type']] = float(row['total'])
        
        for prov in sorted(analytics_totals.keys()):
            dep = analytics_totals[prov]['Deposit']
            wit = analytics_totals[prov]['Withdrawal']
            print(f"{prov:15} | Deposits: ${dep:8.2f} | Withdrawals: ${wit:8.2f}")

if __name__ == "__main__":
    main()
