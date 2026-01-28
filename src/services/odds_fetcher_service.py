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
        'Origin': 'https://www.actionnetwork.com',
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
            # Prefer the newer v2 endpoint for NCAAM/NCAAB so we get the full D1 slate.
            # v1 often returns a subset.
            if api_sport == 'ncaab':
                url = f"https://api.actionnetwork.com/web/v2/scoreboard/ncaab"
                params = {
                    "bookIds": "15,30,79,2988,75,123,71,68,69",
                    "periods": "event",
                    "date": date_str,
                    "division": "D1",
                }
            else:
                url = f"https://api.actionnetwork.com/web/v1/scoreboard/{api_sport}"
                params = {"date": date_str}

            try:
                resp = requests.get(url, params=params, headers=self.HEADERS, timeout=15)
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
            
            # v1: odds lives under game['odds'][0]
            odds_list = game.get('odds', [])
            valid_odd = odds_list[0] if odds_list else {}

            # v2: betting data is under game['markets'][<book_id>]['event'][moneyline/spread/total]
            mk = game.get('markets') or {}
            # Prefer Action book_id 15 (consensus-ish in our pipeline)
            market = mk.get('15') or mk.get(15)
            if market is None and mk:
                # take any market that has an event payload
                market = next(iter(mk.values()))

            home_ml = away_ml = None
            home_sp = away_sp = None
            home_sp_odds = away_sp_odds = None
            total_line = over_odds = under_odds = None

            if isinstance(market, dict):
                ev = market.get('event') or {}

                ml = ev.get('moneyline') or []
                for it in ml:
                    side = it.get('side')
                    if side == 'home':
                        home_ml = it.get('odds')
                    elif side == 'away':
                        away_ml = it.get('odds')

                sp = ev.get('spread') or []
                for it in sp:
                    side = it.get('side')
                    if side == 'home':
                        home_sp = it.get('value')
                        home_sp_odds = it.get('odds')
                    elif side == 'away':
                        away_sp = it.get('value')
                        away_sp_odds = it.get('odds')

                tot = ev.get('total') or []
                for it in tot:
                    side = it.get('side')
                    # both sides share the same total value
                    if total_line is None and it.get('value') is not None:
                        total_line = it.get('value')
                    if side == 'over':
                        over_odds = it.get('odds')
                    elif side == 'under':
                        under_odds = it.get('odds')

            return {
                'game_id': game.get('id'),
                'start_time': game.get('start_time'),
                'status': game.get('status'),
                'home_team': home.get('full_name') or home.get('display_name'),
                'away_team': away.get('full_name') or away.get('display_name'),

                # prefer v2 if present, else v1
                'home_money_line': home_ml if home_ml is not None else valid_odd.get('ml_home'),
                'away_money_line': away_ml if away_ml is not None else valid_odd.get('ml_away'),
                'home_spread': home_sp if home_sp is not None else valid_odd.get('spread_home'),
                'away_spread': away_sp if away_sp is not None else valid_odd.get('spread_away'),
                'home_spread_odds': home_sp_odds if home_sp_odds is not None else valid_odd.get('spread_home_line'),
                'away_spread_odds': away_sp_odds if away_sp_odds is not None else valid_odd.get('spread_away_line'),
                'total_score': total_line if total_line is not None else valid_odd.get('total'),
                'over_odds': over_odds if over_odds is not None else valid_odd.get('over'),
                'under_odds': under_odds if under_odds is not None else valid_odd.get('under'),
            }
        except Exception:
            return None
