import sqlite3
import pandas as pd
import os

def audit_draftkings():
    # Match path logic from database.py
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'bets.db')
    print(f"Connecting to: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Check Tables
    tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", conn)
    print("\n=== Tables in DB ===")
    print(tables)
    
    # 2. Audit DraftKings Financials - Focused on Other
    print("\n=== 'Other' Transactions (DraftKings) ===")
    try:
        query = "SELECT * FROM transactions WHERE provider='DraftKings' AND type NOT IN ('Deposit', 'Withdrawal', 'Wager', 'Winning') ORDER BY date DESC"
        df = pd.read_sql_query(query, conn)
        print(df)
        
        # Check sum of 'Other'
        print(f"Sum of Other: {df['amount'].sum() if not df.empty else 0}")

    except Exception as e:
        print(f"Query Failed: {e}")
    
    conn.close()

if __name__ == "__main__":
    audit_draftkings()
