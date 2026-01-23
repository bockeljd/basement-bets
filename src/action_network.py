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

def get_todays_games(sport, dates_or_weeks, headers=None):
    if headers is None:
        headers = ActionNetworkClient.HEADERS
        
    all_games = []
    api_sport = SPORT_INFO.get(sport, sport)
    
    for date_str in dates_or_weeks:
        try:
            if isinstance(date_str, int):
                url = f"https://api.actionnetwork.com/web/v1/scoreboard/{api_sport}?week={date_str}"
            else:
                url = f"https://api.actionnetwork.com/web/v1/scoreboard/{api_sport}?date={date_str}"
                
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            games_list = data.get('games', [])
            # if games_list:
            #     print(f"[DEBUG] Raw Game Object (First): {games_list[0]}")
            for game in games_list:
                home_team_data = next((box for box in game.get('teams', []) if box['id'] == game['home_team_id']), {})
                away_team_data = next((box for box in game.get('teams', []) if box['id'] == game['away_team_id']), {})
                
                home_team_name = home_team_data.get('full_name', 'Unknown')
                away_team_name = away_team_data.get('full_name', 'Unknown')

                # Odds parsing
                odds_list = game.get('odds', [])
                valid_odd = odds_list[0] if odds_list else {}
                
                # Convert to The Odds API format (or keep raw if preferred, but existing code converts)
                # Event structure
                event = {
                    "id": str(game.get('id')),
                    "sport_key": sport,
                    "home_team": home_team_name,
                    "away_team": away_team_name,
                    "commence_time": game.get('start_time'), # Check format? Usually ISO.
                    "bookmakers": []
                }
                
                # Create a "Consensus" or "ActionNetwork" bookmaker
                if valid_odd:
                    bookmaker = {
                        "key": "actionnetwork",
                        "title": "Action Network (Consensus)",
                        "markets": []
                    }
                    
                    # H2H (Moneyline)
                    outcomes_h2h = []
                    # Check keys validity (ml_home might be None)
                    if valid_odd.get('ml_home') is not None:
                        outcomes_h2h.append({"name": home_team_name, "price": valid_odd.get('ml_home')})
                    if valid_odd.get('ml_away') is not None:
                        outcomes_h2h.append({"name": away_team_name, "price": valid_odd.get('ml_away')})
                    
                    if outcomes_h2h:
                        bookmaker['markets'].append({"key": "h2h", "outcomes": outcomes_h2h})

                    # Spreads
                    outcomes_spread = []
                    if valid_odd.get('spread_home') is not None:
                        outcomes_spread.append({
                            "name": home_team_name, 
                            "price": valid_odd.get('spread_home_line', -110), 
                            "point": valid_odd.get('spread_home')
                        })
                    if valid_odd.get('spread_away') is not None:
                        outcomes_spread.append({
                            "name": away_team_name, 
                            "price": valid_odd.get('spread_away_line', -110), 
                            "point": valid_odd.get('spread_away')
                        })

                    if outcomes_spread:
                        bookmaker['markets'].append({"key": "spreads", "outcomes": outcomes_spread})

                    # Totals
                    outcomes_total = []
                    # Check for total and over/under prices (default -110 if missing but total exists)
                    if valid_odd.get('total') is not None:
                        val_total = valid_odd.get('total')
                        
                        # Over
                        outcomes_total.append({
                            "name": "Over",
                            "point": val_total,
                            "price": valid_odd.get('over', -110)
                        })
                        # Under
                        outcomes_total.append({
                             "name": "Under",
                             "point": val_total,
                             "price": valid_odd.get('under', -110)
                        })
                        
                    if outcomes_total:
                        bookmaker['markets'].append({"key": "totals", "outcomes": outcomes_total})

                    event['bookmakers'].append(bookmaker)
                
                # EXTENSION: Extract Scores if available
                home_score = home_team_data.get('score')
                away_score = away_team_data.get('score')
                
                # Check Boxscore if team data missing score
                if home_score is None:
                    box = game.get('boxscore', {})
                    home_score = box.get('total_home_points')
                    away_score = box.get('total_away_points')

                if home_score is not None and away_score is not None:
                    event['scores'] = [
                        {'name': home_team_name, 'score': str(home_score)},
                        {'name': away_team_name, 'score': str(away_score)}
                    ]

                # EXTENSION: Map Status
                # Action Network status: 'scheduled', 'inprogress', 'complete', 'closed'
                raw_status = game.get('status', 'scheduled')
                event['status'] = raw_status # Keep raw for reference
                if raw_status in ['complete', 'closed', 'final']:
                    event['completed'] = True
                    
                # EXTENSION: Add flat metrics for CSV script
                event['game_id'] = str(game.get('id'))
                if valid_odd:
                    event['home_money_line'] = valid_odd.get('ml_home')
                    event['away_money_line'] = valid_odd.get('ml_away')
                    event['home_spread'] = valid_odd.get('spread_home')
                    event['away_spread'] = valid_odd.get('spread_away')
                    event['home_spread_odds'] = valid_odd.get('spread_home_line')
                    event['away_spread_odds'] = valid_odd.get('spread_away_line')
                    event['over_odds'] = valid_odd.get('over') # check key? usually 'over' or 'total_over'
                    event['under_odds'] = valid_odd.get('under')
                    event['total_score'] = valid_odd.get('total')
                
                all_games.append(event)
                
        except Exception as e:
            print(f"Error fetching {api_sport} for {date_str}: {e}")
            continue

    return all_games

class ActionNetworkClient:
    HEADERS = {
        'Authority': 'api.actionnetwork',
        'Accept': 'application/json',
        'Origin': 'https://www.actionnetwork.com',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
    }

    def fetch_odds(self, sport_key: str, dates: list = None) -> list:
        """
        Fetches odds for a given sport from Action Network.
        Returns a list of dictionaries in a unified format similar to The Odds API.
        """
        # Map TheOddsAPI keys to ActionNetwork keys
        sport_map = {
            "americanfootball_nfl": "nfl",
            "americanfootball_ncaaf": "ncaaf",
            "basketball_nba": "nba",
            "basketball_ncaab": "ncaab",
            "baseball_mlb": "mlb",
            "icehockey_nhl": "nhl",
            "ncaab": "ncaab",
            "ncaaf": "ncaaf",
            "soccer_epl": "soccer", # Map to generic soccer (Action Network usually handles sub-leagues or just 'soccer')
            "soccer": "soccer"
        }
        
        an_sport = sport_map.get(sport_key, sport_key)
        
        if not dates:
            # Get today's date string
            today = datetime.date.today().strftime('%Y%m%d')
            dates = [today]
        
        # Call standalone function
        return get_todays_games(an_sport, dates, headers=self.HEADERS)

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
