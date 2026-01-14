import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import get_db_connection, update_closing_odds
from action_network import ActionNetworkClient, get_todays_games
from datetime import datetime
import time

class ClosingOddsFetcher:
    def __init__(self):
        self.sport_map = {
            "NFL": "nfl",
            "NBA": "nba",
            "NCAAF": "ncaaf",
            "NCAAB": "ncaab",
            "NCAA Basketball": "ncaab",
            "NCAA (Generic)": "ncaab",  # Guessing basketball based on season
            "MLB": "mlb",
            "NHL": "nhl"
        }

    def run(self):
        bets = self._get_pending_clv_bets()
        print(f"Found {len(bets)} bets needing Closing Odds.")
        
        # Group by Date + Sport to minimize API calls
        grouped = {} 
        for bet in bets:
            # Bet date is YYYY-MM-DD HH:MM:SS
            # We need YYYYMMDD for ActionNetwork
            try:
                dt = datetime.strptime(bet['date'], "%Y-%m-%d %H:%M:%S")
            except:
                try: 
                    dt = datetime.strptime(bet['date'], "%Y-%m-%d")
                except:
                    continue
            
            date_key = dt.strftime("%Y%m%d")
            # Inferred sport? 
            # If sport is "Unknown", we might need to guess from description or skip.
            # For now, let's assume NFL/NBA if text allows, or iterate common sports.
            sport = bet['sport'] if bet['sport'] != 'Unknown' else self._infer_sport(bet['description'])
            
            if not sport: continue
            
            key = (date_key, sport)
            if key not in grouped: grouped[key] = []
            grouped[key].append(bet)
            
        print(f"Grouped into {len(grouped)} API batches.")
        
        for (date_str, sport), batch in grouped.items():
            print(f"Fetching {sport} for {date_str} ({len(batch)} bets)...")
            games = get_todays_games(self.sport_map.get(sport, sport), [date_str])
            
            for bet in batch:
                closing_line = self._find_closing_line(bet, games)
                if closing_line:
                    print(f"  Matched Bet {bet['id']}: {bet['selection']} -> CL {closing_line}")
                    update_closing_odds(bet['id'], closing_line)
                else:
                    # print(f"  No match for: {bet['selection']}")
                    pass
            
            time.sleep(1) # Rate limit politeness

    def _get_pending_clv_bets(self):
        query = """
        SELECT * FROM bets 
        WHERE closing_odds IS NULL 
        AND status IN ('WON', 'LOST')
        AND date < date('now')
        ORDER BY date DESC
        LIMIT 50
        """
        with get_db_connection() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]

    def _infer_sport(self, text):
        text = text.lower()
        if "nfl" in text or "chargers" in text or "patriots" in text: return "NFL"
        if "nba" in text or "lakers" in text or "celtics" in text: return "NBA"
        if "college" in text: return "NCAAB"
        return "NFL" # Default fallback for this user's heavy NFL betting

    def _find_closing_line(self, bet, games):
        """
        Matches a bet string to a game result.
        Very basic fuzzy match: checking if Team Name is in Selection.
        And returns the Moneyline odds for now.
        """
        selection = bet['selection']
        if not selection: return None
        
        # Simple Logic: Only Moneyline for now.
        # Iterate games
        for game in games:
            home = game['home_team']
            away = game['away_team']
            
            # Check matches
            matched_team = None
            if self._is_team_match(home, selection):
                matched_team = home
                # Get Home Price
                return self._get_price(game, home)
            elif self._is_team_match(away, selection):
                matched_team = away
                # Get Away Price
                return self._get_price(game, away)
                
        return None

    def _is_team_match(self, team_name, selection):
        # "LA Chargers" vs "Los Angeles Chargers"
        # "Xavier" vs "Xavier"
        # "Purdue" vs "Purdue"
        team_parts = team_name.split()
        selection_parts = selection.split()
        
        # Check if the distinctive part matches
        # E.g. "Chargers" in "LA Chargers"
        # "Xavier" in "Xavier"
        
        # Last word usually robust (Chargers, Eagles, Xavier)
        if team_parts[-1] in selection:
            return True
            
        return False

    def _get_price(self, game, team_name):
        # Look in bookmakers -> markets -> outcomes
        for bm in game.get('bookmakers', []):
            for mkt in bm.get('markets', []):
                if mkt['key'] == 'h2h':
                    for out in mkt.get('outcomes', []):
                        if out['name'] == team_name:
                            return out['price']
        return None

if __name__ == "__main__":
    fetcher = ClosingOddsFetcher()
    fetcher.run()
