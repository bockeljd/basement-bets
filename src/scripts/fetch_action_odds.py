import pandas as pd
import datetime
import os
import sys
import time

# Ensure we can import src
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))

from src.action_network import get_todays_games, SPORT_INFO
from src.database import get_latest_odds_for_diffing, store_odds_snapshots

HEADERS = {
    'Authority': 'api.actionnetwork',
    'Accept': 'application/json',
    'Origin': 'https://www.actionnetwork.com',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
}

def process_sport(sport, dates_or_weeks):
    print(f"\nProcessing {sport}...")
    
    # 0. Global Provider Map (One query to find all relevant AN -> Canonical mappings)
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        id_map_rows = _exec(conn, "SELECT provider_event_id, event_id FROM event_providers WHERE provider = 'actionnetwork'").fetchall()
        an_to_canonical = {str(r['provider_event_id']): r['event_id'] for r in id_map_rows}

    # 1. Fetch Latest State from Postgres
    try:
        baseline_odds = get_latest_odds_for_diffing(sport)
        # Convert to a lookup map for efficient diffing: (event_id, market, side) -> (value, price)
        baseline_map = {
            (str(r['event_id']), r['market_type'], r['side']): (float(r['line_value'] or 0), float(r['price'] or 0))
            for r in baseline_odds
        }
    except Exception as e:
        print(f"Error fetching baseline from DB for {sport}: {e}")
        baseline_map = {}
        
    print(f"Fetching data for {sport}...")
    try:
        games = get_todays_games(sport, dates_or_weeks, HEADERS)
        if not games:
            print(f"No games found for {sport}.")
            return
    except Exception as e:
        print(f"Error fetching data for {sport}: {e}")
        return

    # 2. Extract into Snapshots and Diff
    new_snapshots = []
    now = datetime.datetime.now(datetime.timezone.utc)
    
    for g in games:
        if g.get('status') != 'scheduled':
            continue
            
        an_id = str(g.get('game_id'))
        event_id = an_to_canonical.get(an_id)
        if not event_id:
            # We skip odds for events we haven't canonicalized yet
            continue
            
        # Define markets to track
        markets = [
            ('MONEYLINE', 'home', g.get('home_money_line'), None),
            ('MONEYLINE', 'away', g.get('away_money_line'), None),
            ('SPREAD', 'home', g.get('home_spread_odds'), g.get('home_spread')),
            ('SPREAD', 'away', g.get('away_spread_odds'), g.get('away_spread')),
            ('TOTAL', 'over', g.get('over_odds'), g.get('total_score')),
            ('TOTAL', 'under', g.get('under_odds'), g.get('total_score'))
        ]
        
        for m_type, side, price, line in markets:
            if price is None: continue
            
            # Diff Check
            current_val = (float(line or 0), float(price))
            last_val = baseline_map.get((event_id, m_type, side))
            
            if current_val != last_val:
                new_snapshots.append({
                    "event_id": event_id,
                    "book": "actionnetwork",
                    "market_type": m_type,
                    "side": side,
                    "line_value": line,
                    "price": price,
                    "captured_at": now
                })

    if new_snapshots:
        print(f"Verified {len(new_snapshots)} changed odds for {sport}. Persisting to DB...")
        count = store_odds_snapshots(new_snapshots)
        print(f"Stored {count} snapshots for {sport}.")
    else:
        print(f"No changes detected for {sport}.")


def main():
    # Date-based sports
    today = datetime.date.today()
    date_format = '%Y%m%d'
    # Look back 1 day, forward 3 days
    dates = [(today + datetime.timedelta(days=i)).strftime(date_format) for i in range(-1, 4)]
    
    date_sports = ['nba', 'ncaab', 'soccer', 'mlb']
    
    for sport in date_sports:
        if sport in SPORT_INFO:
            process_sport(sport, dates)
        else:
            print(f"Skipping {sport} (not in SPORT_INFO)")

    # Week-based sports
    # Assuming current time frame implies late season
    weeks = [15, 16, 17, 18, 19, 20] # Extended weeks
    week_sports = ['nfl', 'ncaaf']
    
    for sport in week_sports:
        if sport in SPORT_INFO:
            process_sport(sport, weeks)
        else:
            print(f"Skipping {sport} (not in SPORT_INFO)")

if __name__ == "__main__":
    main()
