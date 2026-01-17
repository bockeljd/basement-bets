
import sys
import os
import sqlite3
from datetime import datetime, timedelta

# Add path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec, update_market_status, get_market_allowlist, init_policy_db
from src.services.policy_engine import PolicyEngine

def verify_curation():
    print("--- Starting Curation Verification ---")
    
    # 0. Init DB Tables if missing
    init_policy_db()
    
    # 1. Reset tables for clean slate
    with get_db_connection() as conn:
        _exec(conn, "DELETE FROM bets WHERE provider = 'MOCK_CURATION'")
        _exec(conn, "DELETE FROM market_performance_daily")
        _exec(conn, "DELETE FROM market_allowlist")
        conn.commit()
        
    # 2. Seed Mock Data (Yesterday)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"Seeding bets for {yesterday}...")
    
    # Scenario A: Spread Market is ON FIRE (30 bets, 60% win rate) -> ROI > 0
    # 30 bets, 1.0u each. 18 Wins, 12 Losses.
    # Profit = (18 * 0.91) - 12 = 16.38 - 12 = 4.38u. Vol = 30u. ROI = 14%.
    
    import uuid
    mock_user_id = str(uuid.uuid4())
    
    bets = []
    for i in range(30):
        status = 'Won' if i < 18 else 'Lost'
        profit = 0.91 if status == 'Won' else -1.0
        bets.append((
            mock_user_id, "MOCK_CURATION", yesterday, "basketball_ncaab", "Spread", 
            1.0, profit, status, f"Mock Spread Bet {i}", "Home -5"
        ))
        
    # Scenario B: Total Market is TRASH (30 bets, 30% win rate) -> ROI < 0
    # 9 Wins, 21 Losses.
    # Profit = (9 * 0.91) - 21 = 8.19 - 21 = -12.8u. ROI = -42%.
    for i in range(30):
        status = 'Won' if i < 9 else 'Lost'
        profit = 0.91 if status == 'Won' else -1.0
        bets.append((
            mock_user_id, "MOCK_CURATION", yesterday, "basketball_ncaab", "Total", 
            1.0, profit, status, f"Mock Total Bet {i}", "Over 150"
        ))
        
    q = """
    INSERT INTO bets (user_id, provider, date, sport, bet_type, wager, profit, status, description, selection)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    # Postgres uses %s logic handled by _exec/db adapter? 
    # But for bulk manual insert let's use loop or safer _exec
    # Assuming standard _exec handles placeholders.
    with get_db_connection() as conn:
        for b in bets:
             _exec(conn, "INSERT INTO bets (user_id, provider, date, sport, bet_type, wager, profit, status, description, selection) VALUES (:u, :p, :d, :s, :bt, :w, :pr, :st, :desc, :sel)", {
                 "u": b[0], "p": b[1], "d": b[2], "s": b[3], "bt": b[4],
                 "w": b[5], "pr": b[6], "st": b[7], "desc": b[8], "sel": b[9]
             })
        conn.commit()
        
    # 3. Run Policy Engine
    print("Running Policy Engine...")
    engine = PolicyEngine()
    engine.refresh_policies()
    
    # 4. Check Results
    allowlist = get_market_allowlist()
    spread_status = allowlist.get(("basketball_ncaab", "Spread"))
    total_status = allowlist.get(("basketball_ncaab", "Total"))
    
    print("\n--- RESULTS ---")
    print(f"Spread Status: {spread_status} (Expected: ENABLED)")
    print(f"Total Status: {total_status} (Expected: SHADOW)")
    
    # Verify DB Aggregation Correctness
    # Check market_performance_daily
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT * FROM market_performance_daily WHERE date = :d", {"d": yesterday}).fetchall()
        print("\n[DB Aggregation Dump]")
        for r in rows:
            print(dict(r))

if __name__ == "__main__":
    verify_curation()
