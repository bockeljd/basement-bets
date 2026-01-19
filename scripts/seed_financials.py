
import sqlite3
import os
from datetime import datetime

# Path to DB
DB_PATH = '/Users/jordanbockelman/Basement Bets/bet_tracker/data/bets.db'

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def exec_query(sql, params=()):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

def main():
    print("Seeding Financial Adjustments...")
    
    # User Provided Targets
    targets = [
        # DraftKings
        {"provider": "DraftKings", "type": "Deposit", "amount": 747.38, "date": "2023-01-01"},
        {"provider": "DraftKings", "type": "Withdrawal", "amount": -1035.38, "date": "2023-12-31"}, # Negative for Withdrawal in DB? Or positive?
        # Check database schema/logic: In analytics.py, it sums abs(amount) for withdrawal if type='Withdrawal'. 
        # But usually transactions store signed values? 
        # Code in analytics.py says: 
        # elif typ == 'Withdrawal': total_withdrawals += abs(amt)
        # So sign doesn't matter for the Calc, but for consistency validation let's use Negative for Withdrawal.
        
        # Barstool
        {"provider": "Barstool", "type": "Deposit", "amount": 58.36, "date": "2023-01-01"},
        {"provider": "Barstool", "type": "Withdrawal", "amount": -89.76, "date": "2023-12-31"},
        
        # FanDuel
        {"provider": "FanDuel", "type": "Deposit", "amount": 120.00, "date": "2023-01-01"},
        {"provider": "FanDuel", "type": "Withdrawal", "amount": -491.34, "date": "2023-12-31"},

        # Other
        # Deposits = 0
        {"provider": "Other", "type": "Withdrawal", "amount": -210.00, "date": "2023-12-31"},
    ]
    
    # 1. Clear existing transactions (since user wants to MATCH this, and table is empty anyway)
    # exec_query("DELETE FROM transactions") # Table is empty found by check, so no need but good for safety.
    
    # 1. Reset Table to ensure schema validity (Since it was 0 rows and schema was mismatching)
    drop_sql = "DROP TABLE IF EXISTS transactions"
    create_sql = """
    CREATE TABLE IF NOT EXISTS transactions (
        txn_id TEXT PRIMARY KEY,
        user_id TEXT,
        account_id TEXT,
        provider TEXT NOT NULL,
        date TEXT NOT NULL,
        type TEXT NOT NULL,
        description TEXT,
        amount REAL NOT NULL,
        balance REAL NOT NULL,
        raw_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    conn = get_db_connection()
    try:
        conn.execute(drop_sql)
        conn.execute(create_sql)
        print("Table 'transactions' dropped and recreated.")

        sql = """
        INSERT INTO transactions (txn_id, user_id, provider, date, type, amount, description, balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        for t in targets:
            # Generate simple ID
            txn_id = f"seed_{t['provider']}_{t['type']}_{abs(t['amount'])}"
            user_id = "manual_seed"
            desc = "Manual Adjustment - User Request"
            # status = "COMPLETED" # Column does not exist
            balance = 0.0 # Placeholder
            
            print(f"Inserting {t['provider']} {t['type']}: {t['amount']}")
            try:
                conn.execute(sql, (txn_id, user_id, t['provider'], t['date'], t['type'], t['amount'], desc, balance))
            except sqlite3.IntegrityError:
                print(" Skipping duplicate...")
            
        conn.commit()
        print("Seeding Complete.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
