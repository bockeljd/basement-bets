import sys
import os
import datetime

# Allow running from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.models.odds_client import OddsAPIClient
from src.services.odds_adapter import OddsAdapter
from src.services.odds_fetcher_service import OddsFetcherService


def ingest_ncaam_sharp_odds(adapter: OddsAdapter) -> dict:
    """Ingest NCAAM sharp benchmark odds (Pinnacle/LowVig/BetOnline) within free-tier budget."""
    client = OddsAPIClient()
    res = client.fetch_ncaam_sharp_odds_budgeted()
    status = str(res.get("status") or "unknown")
    source = str(res.get("source") or "skipped")
    events = res.get("events") or []
    budget = res.get("budget") or {}
    credits_spent = int(res.get("credits_spent") or 0)

    stored_count = 0
    if source == "live" and events:
        stored_count = adapter.normalize_and_store(events, league="NCAAM", provider="odds_api")

    print(
        "[ingest_odds][sharp] "
        f"status={status} source={source} events={len(events)} stored={stored_count} "
        f"spent={credits_spent} day={budget.get('day_credits_used')}/{budget.get('daily_cap')} "
        f"month={budget.get('month_credits_used')}/{budget.get('monthly_budget')} "
        f"api_remaining={budget.get('last_remaining')}"
    )

    try:
        from src.scripts.update_data_health import upsert
        health_status = "ok" if status in ("ok", "cache_fresh", "no_upcoming_games") else "stale"
        row_count = stored_count if source == "live" else len(events)
        notes = (
            f"status={status},source={source},spent={credits_spent},"
            f"day={budget.get('day_credits_used')}/{budget.get('daily_cap')},"
            f"month={budget.get('month_credits_used')}/{budget.get('monthly_budget')},"
            f"remaining={budget.get('last_remaining')}"
        )
        upsert("odds_api_sharp", status=health_status, row_count=int(row_count), notes=notes)
    except Exception as e:
        print(f"[ingest_odds] sharp data_health upsert failed: {e}")

    return res

def main():
    print(f"[{datetime.datetime.now()}] Starting Odds Ingestion...")
    
    adapter = OddsAdapter()
    client = OddsFetcherService()
    
    # Leagues to ingest (add MLB automatically during March-Nov season or explicit env override)
    leagues = ['ncaab', 'nba']
    try:
        mlb_override = os.getenv('INGEST_MLB_ODDS', '').strip().lower()
        in_mlb_window = datetime.datetime.now().month in (3, 4, 5, 6, 7, 8, 9, 10, 11)
        if mlb_override in ('1', 'true', 'yes') or (mlb_override == '' and in_mlb_window):
            leagues.append('mlb')
    except Exception:
        pass
    
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

    # Budget-capped sharp benchmarks for NCAAM (free 500/mo Starter tier guard)
    try:
        ingest_ncaam_sharp_odds(adapter)
    except Exception as e:
        print(f"[ingest_odds] sharp NCAAM ingestion failed (continuing): {e}")

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
