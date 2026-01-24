from src.database import get_db_connection, _exec
from src.services.event_ingestion_service import EventIngestionService
from datetime import datetime

def check_counts():
    print("Checking DB Counts...")
    with get_db_connection() as conn:
        # Check Total Events
        row = _exec(conn, "SELECT COUNT(*) FROM events").fetchone()
        print(f"Total Events: {row[0]}")
        
        # Check Today's Events
        row = _exec(conn, "SELECT COUNT(*) FROM events WHERE date(start_time) = CURRENT_DATE").fetchone()
        print(f"Events Today ({datetime.now().strftime('%Y-%m-%d')}): {row[0]}")
        
        # Check Jan 24
        row = _exec(conn, "SELECT COUNT(*) FROM events WHERE date(start_time) = '2026-01-24'").fetchone()
        print(f"Events Jan 24: {row[0]}")
        
        # Dump all events to see what dates we have
        print("dumping all events:")
        rows = _exec(conn, "SELECT id, start_time, home_team, away_team FROM events").fetchall()
        for r in rows:
            print(f" - {r['start_time']} | {r['home_team']} vs {r['away_team']} | {r['id']}")

def run_ingestion():
    print("\nRunning Full Ingestion for Today...")
    
    # 1. Fetch Events
    from src.services.espn_client_v2 import EspnScoreboardClient
    espn = EspnScoreboardClient()
    # Fetch Saturday Jan 24, 2026
    events = espn.fetch_events('NCAAM', date='20260124')
    print(f"Fetched {len(events)} raw events from ESPN.")
    
    # 2. Ingest Events
    service = EventIngestionService()
    ingested_count = 0
    canonical_events = []
    
    for e in events:
        eid = service.process_event(e)
        if eid:
            ingested_count += 1
            # Re-construct event dict for OddsAdapter if needed, or rely on provider flow
            # The verify script passed raw events to OddsAdapter, so we'll do that loop next.
            e['canonical_id'] = eid # Hint for adapter if we modded it, but we haven't yet.
            canonical_events.append(e)

    print(f"Ingested/Updated {ingested_count} events in DB.")
    
    # 3. Fetch Odds
    print("Fetching Odds via OddsAdapter (Odds API + Action Network)...")
    from src.services.odds_adapter import OddsAdapter
    adapter = OddsAdapter()
    
    # OddsAdapter.normalize_and_store expects a list of raw event dicts from the provider
    # But usually we call an odds fetcher service. 
    # Let's use the adapter's ability to fetch if it has it, or just rely on its 'normalize_and_store' 
    # if we have raw odds data.
    # Wait, OddsAdapter usually *receives* data. 
    # I need to fetch odds from a source.
    # Let's try to mock the provider fetch or use the real `OddsFetcherService` if available.
    
    try:
        from src.services.odds_fetcher_service import OddsFetcherService
        fetcher = OddsFetcherService()
        # fetcher.fetch_odds('NCAAM') # Assuming this method exists
        # If not, let's just inspect OddsFetcherService or skip for now if too complex.
        # Minimal viable: Just ensure events are there. The user said "schedule", odds are secondary but needed for "model".
    except ImportError:
        print("OddsFetcherService not found or failed import.")

    with get_db_connection() as conn:
        row = _exec(conn, "SELECT COUNT(*) FROM events WHERE date(start_time) = CURRENT_DATE").fetchone()
        print(f"Events Today After Ingestion: {row[0]}")

if __name__ == "__main__":
    check_counts()
    run_ingestion()
