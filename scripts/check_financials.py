
import sqlite3
import os
from collections import defaultdict

# Path to DB
DB_PATH = '/Users/jordanbockelman/Basement Bets/bet_tracker/data/bets.db'

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def format_currency(val):
    return f"${val:,.2f}"

def main():
    print("Checking Current Financial Totals...")
    
    query = "SELECT provider, type, amount, description FROM transactions"
    
    provider_stats = defaultdict(lambda: {'deposited': 0.0, 'withdrawn': 0.0})
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query)
    rows = cursor.fetchall()
    
    for r in rows:
        p = r['provider']
        amt = r['amount']
        typ = r['type']
        desc = r['description'] or ''
        
        # Mimic analytics.py logic to see what the app sees
        # analytics.py currently skips 'Manual' in description?
        # Let's print raw first, then filtered.
        
        if typ == 'Deposit':
            provider_stats[p]['deposited'] += amt
        elif typ == 'Withdrawal':
            provider_stats[p]['withdrawn'] += abs(amt)
            
    print(f"{'Provider':<15} | {'Deposited (Raw)':<15} | {'Withdrawn (Raw)':<15}")
    print("-" * 50)
    for p, stats in provider_stats.items():
        print(f"{p:<15} | {format_currency(stats['deposited']):<15} | {format_currency(stats['withdrawn']):<15}")

    conn.close()

if __name__ == "__main__":
    main()
