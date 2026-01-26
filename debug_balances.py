
import os
import sys
from collections import defaultdict
from src.database import get_db_connection

def debug_balances():
    print("--- Debugging Balances ---")
    
    # 1. Check Transactions for explicit 'Balance' entries
    print("\n[1] Checking Transactions with type='Balance'...")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT provider, type, amount, balance, date FROM transactions WHERE type = 'Balance'")
        rows = cur.fetchall()
        if not rows:
            print("  No explicit 'Balance' transactions found.")
        else:
            for r in rows:
                print(f"  Found: {r}")

    # 2. Check Bet Profits by Provider
    print("\n[2] Checking Bet Profits by Provider...")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT provider, SUM(profit) as total_profit, COUNT(*) as count FROM bets GROUP BY provider")
        rows = cur.fetchall()
        for r in rows:
            print(f"  Provider: {r[0]}, Profit: {r[1]}, Count: {r[2]}")

    # 3. Check recent bets (last 5)
    print("\n[3] Recent Bets (Verification)...")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, provider, date, profit, created_at FROM bets ORDER BY created_at DESC LIMIT 5")
        rows = cur.fetchall()
        for r in rows:
            print(f"  Bet: {r}")

if __name__ == "__main__":
    # Ensure we are in the right path/env
    debug_balances()
