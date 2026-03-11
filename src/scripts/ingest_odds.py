import sys
import os
import datetime

# Allow running from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.services.odds_adapter import OddsAdapter
from src.services.odds_fetcher_service import OddsFetcherService

def main():
    print(f"[{datetime.datetime.now()}] Starting Odds Ingestion...")
    
    adapter = OddsAdapter()
    client = OddsFetcherService()
    
    # Leagues to ingest
    leagues = ['ncaab', 'nba'] # Add others if needed: 'nfl', 'nhl'
    
    for league in leagues:
        print(f"Fetching odds for {league}...")
        try:
            # fetch_odds defaults to today's date if not provided
            raw_data = client.fetch_odds(league)

            if not raw_data:
                print(f"No data found for {league}.")
                continue

            # Store (upserts events and odds_snapshots)
            # map 'ncaab' -> 'NCAAM' for adapter if needed
            league_code = "NCAAM" if league == 'ncaab' else league.upper()

            count = adapter.normalize_and_store(raw_data, league=league_code, provider="action_network")
            stats = getattr(adapter, 'last_ingest_stats', None) or {}
            dropped = stats.get('dropped')
            print(f"SUCCESS: Stored {count} snapshots for {league} ({len(raw_data)} games processed)" + (f" | dropped={dropped}" if dropped is not None else ""))

            # Persist a small sanity/quality summary into data_health for the UI.
            try:
                from src.scripts.update_data_health import upsert
                if stats:
                    upsert(
                        f"odds_sanity:{league_code}",
                        status='ok' if count > 0 else 'stale',
                        row_count=int(count) if count is not None else None,
                        notes=str(stats)
                    )
            except Exception as e:
                print(f"[ingest_odds] odds sanity health upsert failed: {e}")

        except Exception as e:
            print(f"ERROR processing {league}: {e}")
            import traceback
            traceback.print_exc()

    # Derived data: market consensus + health status
    try:
        from src.scripts.build_market_consensus import main as build_consensus
        build_consensus()
    except Exception as e:
        print(f"[ingest_odds] build_market_consensus failed: {e}")

    try:
        from src.scripts.update_data_health import main as update_health
        update_health()
    except Exception as e:
        print(f"[ingest_odds] update_data_health failed: {e}")

if __name__ == "__main__":
    main()
