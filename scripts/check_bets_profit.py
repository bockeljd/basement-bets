import sys
import os
import sqlite3

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.database import get_db_connection

def check_bets():
    print("--- CHECKING BETS PROFIT ---")
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # 1. Total Profit
        c.execute("SELECT sum(profit), count(*) FROM bets")
        total, count = c.fetchone()
        print(f"Total Bets: {count}")
        print(f"Total Profit (DB): {total}")
        
        # 2. Wins Profit
        c.execute("SELECT sum(profit), count(*) FROM bets WHERE status='WON'")
        win_prof, win_count = c.fetchone()
        print(f"Won Bets: {win_count} | Profit: {win_prof}")
        
        # 3. Losses Profit
        c.execute("SELECT sum(profit), count(*) FROM bets WHERE status='LOST'")
        loss_prof, loss_count = c.fetchone()
        print(f"Lost Bets: {loss_count} | Profit: {loss_prof}")
        
        # 4. Check a simplified sample of Wins
        c.execute("SELECT date, wager, profit, selection FROM bets WHERE status='WON' LIMIT 5")
        print("\nSample Wins:")
        for r in c.fetchall():
            # handle tuple/dict
            try:
                print(f"{r['date']} | Wager: {r['wager']} | Profit: {r['profit']} | {r['selection']}")
            except:
                print(f"{r[0]} | Wager: {r[1]} | Profit: {r[2]} | {r[3]}")

if __name__ == "__main__":
    check_bets()
