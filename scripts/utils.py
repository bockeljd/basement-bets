import requests
import pandas as pd
import datetime

SPORT_INFO = {
    'nba': 'nba',
    'nfl': 'nfl',
    'mlb': 'mlb',
    'ncaab': 'ncaab',
    'ncaaf': 'ncaaf',
    'soccer': 'soccer'
}

def get_todays_games(sport, dates_or_weeks, headers):
    """
    Fetches games for a given sport over a range of dates.
    dates_or_weeks: list of 'YYYYMMDD' strings.
    """
    all_games = []
    
    # Map valid sports for API
    api_sport = SPORT_INFO.get(sport, sport)
    
    for date_str in dates_or_weeks:
        # Handle "Week" logic if passed integer weeks?
        # User script passes 'dates' like '20260112' OR 'weeks' like [15, 16]
        # Action Network API typically uses dates. For NFL, weeks might need mapped to dates or separate endpoint?
        # Re-checking endpoint: /scoreboard/{sport}?week={week} is possible but date is safer if we know it.
        # However, user passed weeks [15, 16, 17, 18].
        # Let's support both.
        
        try:
            if isinstance(date_str, int):
                # Assume week number
                url = f"https://api.actionnetwork.com/web/v1/scoreboard/{api_sport}?week={date_str}"
            else:
                url = f"https://api.actionnetwork.com/web/v1/scoreboard/{api_sport}?date={date_str}"
                
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            games_list = data.get('games', [])
            for game in games_list:
                # Extract relevant fields
                home_team = next((box for box in game.get('teams', []) if box['id'] == game['home_team_id']), {})
                away_team = next((box for box in game.get('teams', []) if box['id'] == game['away_team_id']), {})
                
                # Odds
                # "odds" list contains dicts with 'ml_home', 'ml_away', 'spread_home', etc.
                # Just take the first valid one or consolidate.
                odds_list = game.get('odds', [])
                valid_odd = odds_list[0] if odds_list else {}
                
                record = {
                    'game_id': game.get('id'),
                    'start_time': game.get('start_time'),
                    'status': game.get('status'),
                    'home_team': home_team.get('full_name'),
                    'away_team': away_team.get('full_name'),
                    'home_score': home_team.get('score'),
                    'away_score': away_team.get('score'),
                    
                    # Odds Metrics
                    'home_money_line': valid_odd.get('ml_home'),
                    'away_money_line': valid_odd.get('ml_away'),
                    'home_spread': valid_odd.get('spread_home'),
                    'away_spread': valid_odd.get('spread_away'),
                    'home_spread_odds': valid_odd.get('spread_home_line'),
                    'away_spread_odds': valid_odd.get('spread_away_line'),
                    'total_score': valid_odd.get('total'),
                    'over_odds': valid_odd.get('over'),
                    'under_odds': valid_odd.get('under'),
                }
                all_games.append(record)
                
        except Exception as e:
            print(f"Error fetching {api_sport} for {date_str}: {e}")
            continue

    return pd.DataFrame(all_games)

def filter_data_on_change(df_combined, dimension_cols, metric_cols):
    """
    Deduplicates data, keeping new rows only if metrics changed.
    """
    # Simply drop duplicates on all dimension + metric cols?
    # User logic implies we check if metrics changed since last scrape.
    # But filtering on change typically means:
    # 1. Sort by time.
    # 2. Group by dimensions (game_id).
    # 3. Check if current row metrics differ from previous row metrics.
    # 4. Keep only changed rows (and the first one).
    
    # Simple Deduplication:
    # Drop pure duplicates first.
    df = df_combined.drop_duplicates(subset=dimension_cols + metric_cols)
    
    # Advanced: If specific logic needed, implement here. 
    # For now, standard dedupe on value columns is sufficient to reduce noise.
    return df
