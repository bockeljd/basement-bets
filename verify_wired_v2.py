import sys
import os
import json
from datetime import datetime

# Adjust path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from src.services.espn_client_v2 import EspnScoreboardClient
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.database import init_db, store_odds_snapshots, get_latest_market_snapshot, fetch_ncaam_analysis_history, get_db_connection, _exec

def verify_wired_integration():
    print("=== NCAAM v2 Wired Integration Verification ===")
    
    # 0. Initialize DB (ensure updated_at, etc.)
    print("\n[Step 0] Initializing DB schema...")
    init_db()
    
    # 1. DB Check
    print("\n[Step 1] Checking `events` and `news_items` tables...")
    with get_db_connection() as conn:
        try:
             _exec(conn, "SELECT * FROM events LIMIT 1")
             print("-> `events` exists.")
        except Exception as e:
             print(f"!! `events` check failed: {e}")
             return

        try:
             _exec(conn, "SELECT * FROM news_items LIMIT 1")
             print("-> `news_items` exists.")
        except Exception as e:
             print(f"!! `news_items` check failed: {e}")
             return

    # 2. Ingestion Check
    print("\n[Step 2] Fetching live events into `events`...")
    espn = EspnScoreboardClient()
    events = espn.fetch_events('NCAAM')
    if not events:
        print("!! No events fetched.")
        return
    
    test_event = events[0]
    print(f"-> Ingested: {test_event['away_team']} @ {test_event['home_team']} (ID: {test_event['id']})")

    # 3. Odds Check
    print("\n[Step 3] Storing mock market snapshot...")
    mock_snap = {
        "event_id": test_event['id'],
        "provider": "draftkings",
        "book": "draftkings", # Added missing key for fingerprinting
        "market_type": "SPREAD",
        "side": "HOME",
        "line_value": -3.5,
        "price": -110,
        "captured_at": datetime.now()
    }
    store_odds_snapshots([mock_snap])
    
    # Verify retrieval (using model's internal flattener)
    model = NCAAMMarketFirstModelV2()
    retrieved_snap = model._get_latest_odds(test_event['id'])
    
    if retrieved_snap and retrieved_snap.get('spread_home'):
        print(f"-> Verified retrieval: Spread {retrieved_snap['spread_home']}")
    else:
        print(f"!! Snapshot flattener failed or data missing. Got: {retrieved_snap}")
        # Not returning here to see if analyze can recover if it handles missing odds
    
    # 4. Model Analysis Check (0.05 Weighting)
    print("\n[Step 4] Running Model v2 Analysis Flow...")
    print(f"-> Model Version: {model.VERSION}")
    print(f"-> Torvik Weight (W_BASE): {model.W_BASE}")
    
    # Passing None for market_snapshot to trigger internal DB lookup
    result = model.analyze(test_event['id'], market_snapshot=None)
    
    print("-> Analysis Narrative Summary:")
    print(f"   {result['narrative']['market_summary']}")
    print(f"   {result['narrative']['recommendation']}")
    
    # 5. History Persistence Check
    print("\n[Step 5] Verifying History Persistence via `events` join...")
    history = fetch_ncaam_analysis_history(limit=5)
    found = any(h['event_id'] == test_event['id'] for h in history)
    
    if found:
        print("-> Success! Analysis found in history table (Joined correctly).")
    else:
        print("!! Persistence/Join failed.")

    print("\n=== Verification Complete! ===")

if __name__ == "__main__":
    verify_wired_integration()
