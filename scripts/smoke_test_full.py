
import sys
import os
import json
import uuid
import math
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.database import get_db_connection, _exec, init_db, fetch_model_history, update_model_prediction_result
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.services.odds_adapter import OddsAdapter
from src.services.grading_service import GradingService

def smoke_test():
    print("=== STARTING SMOKE TEST ===")
    
    # 1. Init DB (Ensure Schema)
    # Note: This might clear tables if reset env is set? Assuming safe init.
    # We won't call full init_db to avoid dropping unless necessary.
    # Just assume DB is up.
    
    event_id = f"smoke_evt_{uuid.uuid4().hex[:8]}"
    print(f"[1] Creating Synthetic Event: {event_id}")
    
    suffix = uuid.uuid4().hex[:4]
    home_team = f"Smoke Home {suffix}"
    away_team = f"Smoke Away {suffix}"
    
    ev_data = {
        "id": event_id,
        "sport_key": "NCAAM",
        "league": "NCAAM",
        "home_team": home_team,
        "away_team": away_team,
        "start_time": (datetime.now() + timedelta(hours=2)).isoformat(), 
        "status": "STATUS_SCHEDULED"
    }
    
    # Direct insert
    q_ev = """
    INSERT INTO events (id, league, home_team, away_team, start_time, status)
    VALUES (:id, :league, :home_team, :away_team, :start_time, :status)
    ON CONFLICT (id) DO NOTHING
    """
    with get_db_connection() as conn:
        _exec(conn, q_ev, ev_data)
        
        # Manually ensure job_runs exists (init_jobs_db fallback)
        _exec(conn, """
        CREATE TABLE IF NOT EXISTS job_runs (
            id BIGSERIAL PRIMARY KEY,
            job_name TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'running',
            detail JSONB,
            error TEXT
        );
        """)
        conn.commit()
        
    # 2. Insert Odds (via Adapter)
    print("[2] Inserting Odds via Adapter...")
    adapter = OddsAdapter()
    
    # Mock Raw Data from Provider (Action Network style)
    raw_odds = [{
        "home_team": home_team,
        "away_team": away_team,
        "start_time": ev_data['start_time'], # String ISO
        "home_spread": -5.5,
        "home_spread_odds": -110,
        "away_spread_odds": -110,
        "total_score": 145.0,
        "over_odds": -110,
        "under_odds": -110
    }]
    
    # This should resolve to our event_id via name matching in SQL
    count = adapter.normalize_and_store(raw_odds, "NCAAM", provider="action_network")
    print(f"    Ingested: {count} snapshots.")
    if count == 0:
        print("FAIL: Zero snapshots ingested. Logic broken?")
        # Force manual snapshot insert for rest of test if Adapter fails?
        # But we want to test Adapter.
        # Maybe fuzzy match failed?
        # Names are exact.
        pass
        
    # 3. Run Analysis
    print("[3] Running Model Analysis...")
    model = NCAAMMarketFirstModelV2()
    # Force result even if adapter failed (by manually ensuring snapshots exist?)
    # Let's check snapshots for event
    with get_db_connection() as conn:
        c = _exec(conn, "SELECT count(*) as cnt FROM odds_snapshots WHERE event_id=:eid", {"eid": event_id}).fetchone()
        print(f"    DB Verification: {c['cnt']} snapshots found for {event_id}")
        
    result = model.analyze(event_id)
    
    print("    Analysis Result Keys:", result.keys())
    print(f"    Analysis Returned Event ID: {result.get('event_id')}")
    
    # Check what IS in snapshots
    with get_db_connection() as conn:
        snaps = _exec(conn, "SELECT event_id, count(*) as c FROM odds_snapshots GROUP BY event_id").fetchall()
        print("    DB Snapshots Grouped:", [dict(s) for s in snaps])
    
    if "error" in result:
        print(f"FAIL: Analysis returned error: {result['error']}")
        sys.exit(1)
        
    # Check Prediction Persistence
    pred_counts = fetch_model_history(limit=50)
    # print("    History Items:", [f"{p['event_id']} ({p['market_type']})" for p in pred_counts])
    
    # Check if our event is in history
    found = any(p['event_id'] == event_id for p in pred_counts)
    print(f"    Persistence Validated: {found}")
    
    # 4. Grading Logic
    print("[4] Testing Gradient/Settlement...")
    # Manually set result to FINAL
    res_data = {
        "event_id": event_id,
        "home_score": 80,
        "away_score": 70, # Home Wins by 10. Covers -5.5. Total 150 (Over 145).
        "final": True,
        "period": "FINAL"
    }
    from src.database import upsert_game_result
    upsert_game_result(res_data)
    
    # Trigger Grading
    grader = GradingService()
    # We call _evaluate_db_predictions directly or grade_predictions
    stats = grader.grade_predictions()
    print("    Grading Stats:", stats)
    
    # Verify Outcome
    # We need to see if the prediction for this event was updated to WON/LOST.
    # Note: model.analyze picks BEST Recommendation.
    # If Home covers (-5.5), and model picked Home, outcome should be WON.
    
    with get_db_connection() as conn:
        row = _exec(conn, "SELECT outcome, pick, market_type FROM model_predictions WHERE event_id=:eid", {"eid": event_id}).fetchone()
        if row:
            print(f"    Final Outcome: {row['pick']} ({row['market_type']}) -> {row['outcome']}")
        else:
            print("FAIL: Prediction row missing?")

    print("=== SMOKE TEST COMPLETE ===")

if __name__ == "__main__":
    smoke_test()
