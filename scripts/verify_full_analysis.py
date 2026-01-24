
import sys
import os
import json
import uuid
from datetime import datetime

# Path setup
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.database import get_db_connection, _exec, init_db
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

def verify_analysis():
    print("--- End-to-End Analysis Verification ---")
    
    # 1. Setup Test Data
    event_id = f"test_evt_{uuid.uuid4().hex[:8]}"
    print(f"[Setup] Creating test event: {event_id}")
    
    # Create Event
    with get_db_connection() as conn:
        _exec(conn, """
            INSERT INTO events (id, league, home_team, away_team, start_time, status)
            VALUES (:id, 'NCAAM', 'Duke', 'North Carolina', NOW() + INTERVAL '1 day', 'SCHEDULED')
            ON CONFLICT (id) DO NOTHING
        """, {"id": event_id})
        conn.commit()
    
    # Create Odds using helper
    from src.database import insert_odds_snapshot
    insert_odds_snapshot({
        "event_id": event_id,
        "book": "DraftKings",
        "market_type": "SPREAD",
        "side": "HOME",
        "line_value": -3.5,
        "price": -110,
        "captured_at": datetime.now().isoformat()
    })
    insert_odds_snapshot({
        "event_id": event_id,
        "book": "DraftKings",
        "market_type": "TOTAL",
        "side": "OVER",
        "line_value": 150.5,
        "price": -110,
        "captured_at": datetime.now().isoformat()
    })
        
    # 2. Run Analysis
    print("[Action] Running Model Analysis...")
    try:
        model = NCAAMMarketFirstModelV2()
        # Mock Torvik Service to avoid external calls
        model.torvik_service.get_projection = lambda h, a: {"margin": 4.5, "total": 152.0, "official_margin": 4.5}
        
        result = model.analyze(event_id)
        
        if result.get("error"):
            print(f"[Fail] Analysis returned error: {result['error']}")
            sys.exit(1)
            
        print("[Pass] Analysis returned result.")
        print(f"   Fair Line: {result.get('fair_line')}")
        print(f"   Edge: {result.get('edge_points')}")
        print(f"   Recs: {len(result.get('recommendations', []))}")
        
    except Exception as e:
        print(f"[Fail] Analysis crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # 3. Verify Persistence
    print("[Check] Verifying Database persistence...")
    with get_db_connection() as conn:
        row = _exec(conn, "SELECT count(*) FROM model_predictions WHERE event_id = :eid", {"eid": event_id}).fetchone()
        if row[0] > 0:
            print(f"[Pass] Prediction saved to DB. Count: {row[0]}")
        else:
            print("[Fail] Prediction NOT saved to DB.")
            sys.exit(1)

if __name__ == "__main__":
    verify_analysis()
