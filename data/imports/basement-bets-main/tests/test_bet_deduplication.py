import sqlite3
import os
from src.database import get_db_connection, insert_bet, _exec

def test_deduplication_logic():
    """
    Verifies that the UNIQUE constraint on the bets table prevents duplicate ingestion.
    """
    
    # Mock bet data
    bet = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "provider": "DK",
        "date": "2026-01-14",
        "sport": "NFL",
        "bet_type": "Spread",
        "wager": 110.0,
        "profit": 100.0,
        "status": "PENDING",
        "description": "Chiefs vs 49ers",
        "selection": "Chiefs -2.5",
        "odds": -110,
        "is_live": False,
        "is_bonus": False,
        "raw_text": "Sample Slip Text",
        "account_id": "00000000-0000-0000-0000-000000000002"
    }
    
    print("Running Bet Deduplication Tests...")
    
    with get_db_connection() as conn:
        # 1. Clean up any existing test data
        _exec(conn, "DELETE FROM bets WHERE description = :desc", {"desc": "Chiefs vs 49ers"})
        conn.commit()
        
        # 2. First Ingestion
        print("  Inserting first bet...")
        insert_bet(bet)
        
        cursor = _exec(conn, "SELECT count(*) as count FROM bets WHERE description = :desc", {"desc": "Chiefs vs 49ers"})
        count = cursor.fetchone()['count']
        assert count == 1, f"Expected 1 bet, found {count}"
        
        # 3. Second Ingestion (Exact Duplicate)
        print("  Attempting second insertion (duplicate)...")
        # insert_bet uses INSERT OR IGNORE, so it should not throw but should not add a row
        insert_bet(bet)
        
        cursor = _exec(conn, "SELECT count(*) as count FROM bets WHERE description = :desc", {"desc": "Chiefs vs 49ers"})
        count = cursor.fetchone()['count']
        assert count == 1, f"Expected still 1 bet after duplicate ingestion, found {count}"
        
        # 4. Modify one unique field (e.g. wager) - should allow insertion
        print("  Inserting modified bet (different wager)...")
        bet_new = bet.copy()
        bet_new['wager'] = 111.0
        insert_bet(bet_new)
        
        cursor = _exec(conn, "SELECT count(*) as count FROM bets WHERE description = :desc", {"desc": "Chiefs vs 49ers"})
        count = cursor.fetchone()['count']
        assert count == 2, f"Expected 2 bets after modification, found {count}"
        
    print("Bet Deduplication Tests Passed!")

if __name__ == "__main__":
    test_deduplication_logic()
