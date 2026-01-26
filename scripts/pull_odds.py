import pandas as pd
import datetime
import os
import sys
import time

# Ensure we can import utils and src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import get_todays_games, filter_data_on_change, SPORT_INFO

HEADERS = {
    'Authority': 'api.actionnetwork',
    'Accept': 'application/json',
    'Origin': 'https://www.actionnetwork.com',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
}

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../data/bets_db'))

def process_sport(sport, dates_or_weeks):
    print(f"\nProcessing {sport}...")
    
    # ensure data dir exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    db_path = os.path.join(DATA_DIR, f'{sport}_bets_db.csv')
    
    if os.path.exists(db_path):
        try:
            df_all = pd.read_csv(db_path)
            # Ensure date_scraped is datetime
            if 'date_scraped' in df_all.columns:
                df_all['date_scraped'] = pd.to_datetime(df_all['date_scraped'])
        except Exception as e:
            print(f"Error reading existing DB for {sport}: {e}")
            df_all = pd.DataFrame()
    else:
        df_all = pd.DataFrame()
        
    print(f"Fetching data for {sport}...")
    try:
        df_new = get_todays_games(sport, dates_or_weeks, HEADERS)
    except Exception as e:
        print(f"Error fetching data for {sport}: {e}")
        return

    if df_new is None or df_new.empty:
        print(f"No new data found for {sport}.")
        return

    # Add timestamp
    df_new['date_scraped'] = datetime.datetime.now()
    
    # Filter for scheduled games (like in the template)
    # But user asked to pull data and save on changes. 
    # If we filter only scheduled, we miss completed game results updates if they matter.
    # However, keeping it consistent with the template:
    # if 'status' in df_new.columns:
    #     df_new = df_new.loc[df_new['status'] == 'scheduled']
    
    if df_new.empty:
        print(f"No scheduled games found for {sport}.")
        return

    print(f"Found {len(df_new)} new rows.")
    
    # Concatenate
    df_combined = pd.concat([df_all, df_new], ignore_index=True)
    
    # Filter on change
    # check available columns
    dimension_cols = ['game_id', 'home_team', 'away_team']
    
    # Potential metric columns
    possible_metrics = [
        'home_money_line', 'away_money_line', 'total_score',
        'home_spread', 'away_spread', 
        'home_spread_odds', 'away_spread_odds',
        'over_odds', 'under_odds'
    ]
    
    metric_cols = [c for c in possible_metrics if c in df_combined.columns]
    
    if not metric_cols:
        print(f"Warning: No metric columns found for {sport}. Saving all data.")
        filtered_df = df_combined
    else:
        print(f"Filtering on change using metrics: {metric_cols}")
        # Ensure sorting by date_scraped to keep change logic correct
        if 'date_scraped' in df_combined.columns:
            df_combined = df_combined.sort_values('date_scraped')
            
        try:
            filtered_df = filter_data_on_change(df_combined, dimension_cols, metric_cols)
        except Exception as e:
            print(f"Error filtering data: {e}. Saving all.")
            filtered_df = df_combined

    print(f"Saving {len(filtered_df)} rows to {db_path} (was {len(df_all)})")
    filtered_df.to_csv(db_path, index=False)
    
    # NEW: Ingest into odds_snapshots table
    try:
        from src.services.odds_adapter import OddsAdapter
        adapter = OddsAdapter()
        # Convert DataFrame to list of dicts
        # Sanitize NaNs (Postgres rejects NaN)
        df_clean = filtered_df.where(pd.notnull(filtered_df), None)
        raw_data = df_clean.to_dict('records')
        
        # Map to canonical league
        league_map = {
            'nfl': 'NFL',
            'ncaaf': 'NCAAF',
            'nba': 'NBA',
            'ncaab': 'NCAAM',
            'mlb': 'MLB',
            'soccer': 'SOCCER'
        }
        canonical_league = league_map.get(sport, sport.upper())
        
        count = adapter.normalize_and_store(raw_data, league=canonical_league, provider="action_network")
        print(f"Ingested {count} snapshots into database for {canonical_league}.")
    except Exception as e:
        print(f"Database Ingestion Error: {e}")


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
    # For now, let's just use current dates for NFL too if API supports it, 
    # or rely on hardcoded weeks (as provided by user)
    
    # Current date is 2026-01-12. This is likely Week 18 or WildCard.
    # VegasInsider showed Wild Card for 2026.
    # Week 18 is typically early Jan. Wild Card mid Jan.
    # The snippet has `weeks = [15, 16, 17, 18]`. These are past weeks in 2026 Jan? 
    # Or upcoming? Jan 12 is likely playoffs.
    # I'll keep user's code but maybe add Wild Card (Week 19?) if needed.
    # Or just rely on dates if `utils.py` handles int vs str correctly.
    
    weeks = [15, 16, 17, 18]
    week_sports = ['nfl', 'ncaaf']
    
    for sport in week_sports:
        if sport in SPORT_INFO:
            process_sport(sport, weeks)
        else:
            print(f"Skipping {sport} (not in SPORT_INFO)")

if __name__ == "__main__":
    main()
