import requests
import datetime
from typing import List, Dict, Optional

class OddsFetcherService:
    """
    Fetches odds from Action Network (primary).
    """
    HEADERS = {
        'Authority': 'api.actionnetwork.com',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
    }
    
    SPORT_MAP = {
        'NBA': 'nba',
        'NFL': 'nfl',
        'MLB': 'mlb',
        'NCAAM': 'ncaab',
        'NCAAF': 'ncaaf',
        'EPL': 'soccer'
    }

    def fetch_odds(self, league: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        Fetch odds for a league over a date range.
        Dates in 'YYYYMMDD' format.
        """
        api_sport = self.SPORT_MAP.get(league, league.lower())
        
        # Determine Date Range
        if not start_date:
            today = datetime.date.today()
            dates = [today.strftime("%Y%m%d")]
        else:
            dates = [start_date] # TODO: Expand range if start!=end
            if end_date and end_date != start_date:
                # Basic expansion or just support list
                # For MVP, just specific dates or single date
                pass

        all_games = []
        for date_str in dates:
            url = f"https://api.actionnetwork.com/web/v1/scoreboard/{api_sport}?date={date_str}"
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                
                games = data.get('games', [])
                for game in games:
                   parsed = self._parse_game(game)
                   if parsed:
                       all_games.append(parsed)
            except Exception as e:
                print(f"[OddsFetcher] Error fetching {league} on {date_str}: {e}")
                
        return all_games

    def _parse_game(self, game: Dict) -> Optional[Dict]:
        try:
            home = next((t for t in game.get('teams', []) if t['id'] == game['home_team_id']), {})
            away = next((t for t in game.get('teams', []) if t['id'] == game['away_team_id']), {})
            
            odds_list = game.get('odds', [])
            valid_odd = odds_list[0] if odds_list else {}
            
            return {
                'game_id': game.get('id'),
                'start_time': game.get('start_time'),
                'status': game.get('status'),
                'home_team': home.get('full_name'),
                'away_team': away.get('full_name'),
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
        except Exception:
            return None
