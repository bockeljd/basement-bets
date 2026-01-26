
import sys
import os

# Ensure src is in path
sys.path.append(os.getcwd())

from src.analytics import AnalyticsEngine
from src.database import get_db_connection

def verify():
    print("--- Verifying Analytics Fix ---")
    engine = AnalyticsEngine()
    balances = engine.get_balances()
    print("Current Balances:")
    print(balances)
    
    # Check if there are pending bets after the snapshot date
    # Snapshot dates: DK (Jan 24), FD (Jan 24)
    # Check for bets > Jan 24
    
    print("\nChecking for post-snapshot bets...")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT provider, date, status, wager, profit, created_at FROM bets WHERE created_at > '2026-01-24'")
        rows = cur.fetchall()
        for r in rows:
            print(f"  {r}")

if __name__ == "__main__":
    verify()
