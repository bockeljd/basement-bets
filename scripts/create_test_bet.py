
import sys
import os
from datetime import datetime
import uuid

# Ensure root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec

def create_bet():
    # Target: UNC Wilmington (Home) vs Hampton Pirates (Away) - 2026-01-04
    # Score: 49-45 (Confirms Home Win, Total 94)
    
    bet_uuid = str(uuid.uuid4())
    user_id = str(uuid.uuid4()) # Use UUID for Postgres compat
    
    print(f"Creating Test Bet {bet_uuid}...")
    
    with get_db_connection() as conn:
        # Insert Slip
        # Omit ID to let AutoInc handle it (if Serial/Integer)
        # Use RETURNING id to get it back for legs.
        cur = _exec(conn, """
            INSERT INTO bets (user_id, provider, date, sport, bet_type, wager, profit, status, is_parlay, hash_id, description)
            VALUES (:uid, 'MANUAL', '2026-01-04', 'NCAAM', 'PARLAY', 10.0, 0.0, 'PENDING', TRUE, :hid, 'Test Parlay')
            RETURNING id
        """, {
            "uid": user_id, "hid": f"test_hash_{bet_uuid}"
        })
        
        # Fetch ID
        res = cur.fetchone()
        if res:
            # Handle row lookup safely for dict cursor or tuple
            actual_bet_id = res['id'] if hasattr(res, 'keys') else res[0]
        else:
            raise Exception("Failed to insert bet")
            
        print(f"Created Bet ID: {actual_bet_id}")
        
        # Leg 1: Moneyline Home (UNC Wilmington)
        _exec(conn, """
            INSERT INTO bet_legs (bet_id, selection, leg_type, market_key, status)
            VALUES (:bid, 'UNC Wilmington Seahawks', 'MONEYLINE', 'moneyline', 'PENDING')
        """, {"bid": actual_bet_id})
        
        # Leg 2: Spread Home -2.5 (UNC Wilmington -2.5)
        _exec(conn, """
            INSERT INTO bet_legs (bet_id, selection, leg_type, market_key, line_value, status)
            VALUES (:bid, 'UNC Wilmington Seahawks -2.5', 'SPREAD', 'spread', -2.5, 'PENDING')
        """, {"bid": actual_bet_id})
        
        # Leg 3: Total Over 90
        _exec(conn, """
            INSERT INTO bet_legs (bet_id, selection, leg_type, market_key, line_value, status)
            VALUES (:bid, 'Over 90', 'TOTAL', 'total', 90.0, 'PENDING')
        """, {"bid": actual_bet_id})
        
        conn.commit()
    
    print("Test Bet Created.")

if __name__ == "__main__":
    create_bet()
