
import sys
import os
import sqlite3
from datetime import datetime, timedelta

# Add path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec, calc_market_features, get_market_features, init_odds_snapshots_db
from src.models.ncaam_model import NCAAMModel
from src.models.schemas import MarketSnapshot, Signal

def verify_features():
    print("--- Starting Market Features Verification ---")
    
    # 0. Init DB (ensure table exists)
    init_odds_snapshots_db()
    
    # 1. Reset
    game_id = "test_game_123"
    with get_db_connection() as conn:
        _exec(conn, "DELETE FROM odds_snapshots WHERE event_id = :gid", {"gid": game_id})
        _exec(conn, "DELETE FROM market_line_features WHERE game_id = :gid", {"gid": game_id})
        conn.commit()
        
    # 2. Seed Snapshots (Steam Move towards Home)
    # Open: -4.5 at 10:00
    # Current: -6.5 at 12:00
    # Movement: -2.0 (Home favored more)
    
    now = datetime.now()
    t1 = now - timedelta(hours=2)
    t2 = now
    
    snaps = [
        # Open
        {"gid": game_id, "bk": "dk", "mt": "Spread", "sd": "Home", "ln": -4.5, "pr": -110, "ca": t1},
        # Current
        {"gid": game_id, "bk": "dk", "mt": "Spread", "sd": "Home", "ln": -6.5, "pr": -110, "ca": t2},
    ]
    
    q_ins = """
    INSERT INTO odds_snapshots (event_id, book, market_type, side, line, price, captured_at, captured_bucket)
    VALUES (:gid, :bk, :mt, :sd, :ln, :pr, :ca, :ca)
    """
    
    with get_db_connection() as conn:
        for s in snaps:
            _exec(conn, q_ins, s)
        conn.commit()
        
    print("Seeded Odds Snapshots (Move -4.5 -> -6.5).")
    
    # 3. Calculate Features
    calc_market_features(game_id)
    
    # 4. Verify DB
    feats = get_market_features(game_id)
    print(f"Features Retrieved: {feats}")
    
    spread_feat = feats.get("Spread")
    if not spread_feat:
        print("FAIL: No Spread features found.")
        return
        
    move = spread_feat['line_movement']
    print(f"Line Movement: {move} (Expected: -2.0)")
    
    if abs(move - (-2.0)) < 0.1:
        print("PASS: Movement calculation correct.")
    else:
        print("FAIL: Movement calculation incorrect.")
        
    # 5. Verify Model Impact
    # Create Signal manually to test logic (mimicking find_edges)
    # Move is -2.0. Impact = -2.0 * -0.5 = +1.0 (Boost Home).
    
    sig = Signal(
        source="MARKET_MOVE", 
        category="MARKET",
        description="Test Signal",
        target="HOME", 
        impact_points=1.0, 
        confidence=0.8
    )
    
    model = NCAAMModel()
    
    # Predict WITHOUT Signal
    market = MarketSnapshot(spread_home=-6.5, total_line=150.0)
    # Stats: Equal teams (0 margin base)
    model.team_stats = {
        "TeamA": {"eff_off": 100, "eff_def": 100, "tempo": 70},
        "TeamB": {"eff_off": 100, "eff_def": 100, "tempo": 70}
    }
    
    # Base prediction (should be ~HFA +3.2)
    base = model.predict_v1("TeamA", "TeamB", market)
    score_diff_base = base.prediction.score_home - base.prediction.score_away
    print(f"Base Margin (No Signal): {score_diff_base:.2f}")
    
    # Predict WITH Signal
    boosted = model.predict_v1("TeamA", "TeamB", market, signals=[sig])
    score_diff_boost = boosted.prediction.score_home - boosted.prediction.score_away
    print(f"Boosted Margin (With Signal): {score_diff_boost:.2f}")
    
    diff = score_diff_boost - score_diff_base
    print(f"Signal Impact: {diff:.2f} (Expected: +1.0)")
    
    if abs(diff - 1.0) < 0.1:
        print("PASS: Signal integrated correctly.")
    else:
        print("FAIL: Signal not applied.")

if __name__ == "__main__":
    verify_features()
