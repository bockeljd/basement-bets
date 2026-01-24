import sys
import os
import json
from datetime import datetime

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.parsers.espn_client import EspnClient
from src.services.odds_fetcher_service import OddsFetcherService
from src.services.odds_adapter import OddsAdapter
from src.services.game_analyzer import GameAnalyzer
from src.database import get_db_connection

def validate_full_pipeline():
    print("=== Start End-to-End Model Validation Walkthrough ===\n")
    league = "NCAAM"
    date_str = datetime.now().strftime("%Y%m%d")

    # 1. Ingest Schedule
    print("[1/4] Ingesting Live Schedule (ESPN)...")
    espn = EspnClient()
    events = espn.fetch_scoreboard(league, date=date_str)
    print(f"  Fetched {len(events)} events from ESPN.")

    if not events:
        print("!! No events found for today. Cannot proceed with validation.")
        return

    # 2. Ingest Odds
    print("\n[2/4] Ingesting Live Odds (Action Network)...")
    fetcher = OddsFetcherService()
    adapter = OddsAdapter()
    
    raw_odds = fetcher.fetch_odds(league, start_date=date_str)
    print(f"  Fetched {len(raw_odds)} game odds.")
    
    snap_count = adapter.normalize_and_store(raw_odds, league=league, provider="action_network")
    print(f"  Stored {snap_count} odds snapshots in database.")
    
    # 3. Pick a Game for Analysis
    if not events:
        print("!! No events found for today. Cannot proceed with analysis validation.")
        return

    game = events[0]
    game_id = game['id']
    home_team = game['home_team']
    away_team = game['away_team']
    print(f"\n[3/4] Running Analysis for: {away_team} @ {home_team} (ID: {game_id})")
    
    analyzer = GameAnalyzer()
    try:
        result = analyzer.analyze(
            game_id=game_id,
            sport=league,
            home_team=home_team,
            away_team=away_team
        )
        print("\nAnalysis Result Details:")
        print(f"  Narrative: {result['narrative']}")
        print(f"  Recommendations: {json.dumps(result['recommendations'], indent=4)}")
        
        # 4. Verify DB Persistence
        print("\n[4/4] Verifying DB Persistence...")
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Need to use %s for Postgres or ? for SQLite logic? 
                # src.database._exec handles this, but let's be direct or use _exec.
                from src.database import _exec
                cursor = _exec(conn, "SELECT * FROM model_predictions WHERE game_id = :gid", {"gid": game_id})
                row = cursor.fetchone()
                if row:
                    print(f"  SUCCESS: Prediction found in model_predictions.")
                    print(f"  Bet On: {row['bet_on']}, Market: {row['market']}, Line: {row['market_line']}")
                else:
                    print("  FAILURE: Prediction not found in database.")
                    
    except Exception as e:
        print(f"!! Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    validate_full_pipeline()
