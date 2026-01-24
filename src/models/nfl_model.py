import math
from typing import Dict, Any, List
from src.models.base_model import BaseModel

# Pure Python Norm CDF (Error Function)
def norm_cdf(x, mu=0.0, sigma=1.0):
    val = (x - mu) / sigma
    return (1.0 + math.erf(val / math.sqrt(2.0))) / 2.0

class NFLModel(BaseModel):
    def __init__(self):
        super().__init__(sport_key="americanfootball_nfl")
        self.team_ratings = {} # Map of team -> rating

    def fetch_data(self):
        """
        Loads 2026 Predictive Power Ratings (Scraped Jan 17, 2026).
        Source: TeamRankings (Points Above Average).
        """
        self.team_ratings = {
            "Seattle Seahawks": 8.6,
            "Los Angeles Rams": 8.6,
            "Houston Texans": 6.8,
            "Buffalo Bills": 5.6,
            "Jacksonville Jaguars": 5.6,
            "New England Patriots": 4.7,
            "Detroit Lions": 4.5,
            "San Francisco 49ers": 4.2,
            "Philadelphia Eagles": 3.7,
            "Denver Broncos": 3.2,
            "Baltimore Ravens": 2.8,
            "Kansas City Chiefs": 2.8,
            "Indianapolis Colts": 2.3,
            "Green Bay Packers": 2.1,
            "Minnesota Vikings": 1.2,
            "Chicago Bears": 1.1,
            "Los Angeles Chargers": 0.9,
            "Pittsburgh Steelers": -0.1,
            "Tampa Bay Buccaneers": -0.8,
            "Atlanta Falcons": -2.7,
            "Dallas Cowboys": -2.8,
            "Cincinnati Bengals": -2.9,
            "Washington Commanders": -3.5,
            "New York Giants": -3.6,
            "Carolina Panthers": -3.7,
            "Arizona Cardinals": -4.4,
            "Miami Dolphins": -5.0,
            "New Orleans Saints": -5.8,
            "Cleveland Browns": -6.2,
            "Tennessee Titans": -8.3,
            "Las Vegas Raiders": -8.6,
            "New York Jets": -10.3
        }

    def predict(self, game_id: str, home_team: str, away_team: str, market_spread: float = 0) -> Dict[str, Any]:
        """
        Simplistic NFL Spread Model:
        Predicted Margin = (Home Rating - Away Rating) + Home Field Advantage (approx 1.5 - 2.0 pts)
        """
        if not self.team_ratings:
            self.fetch_data()

        h_rate = self.team_ratings.get(home_team, 0.0)
        a_rate = self.team_ratings.get(away_team, 0.0)
        
        home_field = 1.8 
        raw_margin = (h_rate - a_rate) + home_field
        
        # Convert Margin to Spread Win Prob
        std_dev = 13.5
        
        # Prob cover: Margin vs -Spread (since spread is usually -7.5 for favorite)
        win_prob_cover = 1.0 - norm_cdf(-market_spread, mu=raw_margin, sigma=std_dev)
        
        fair_spread = round(-raw_margin * 2) / 2
        
        return {
            "game_id": game_id,
            "fair_spread": fair_spread,
            "win_prob": win_prob_cover,
            "edge": abs(fair_spread - market_spread), # Point Edge
            "model_version": "2024-01-14-nfl-v1"
        }

    def _calculate_implied_prob_from_odds(self, american_odds: int) -> float:
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)

    def find_edges(self):
        """
        Fetches current odds and identifies edges.
        """
        from src.models.odds_client import OddsAPIClient
        client = OddsAPIClient()
        
        # Fetch live NFL odds (fallback to Action Network is automatic in client)
        odds = client.get_odds("americanfootball_nfl", regions="us", markets="spreads")
        
        edges = []
        for game in odds:
            game_id = game.get('id')
            home_team = game.get('home_team')
            away_team = game.get('away_team')
            
            # Find Best Spread Market
            best_market = None
            bookmakers = game.get('bookmakers', [])
            target_books = ['draftkings', 'fanduel', 'betmgm']
            
            for book in bookmakers:
                if book['key'] in target_books:
                    for m in book['markets']:
                        if m['key'] == 'spreads':
                            best_market = m
                            break
                if best_market: break
                
            if not best_market or not best_market.get('outcomes'):
                # Try fallback to any book
                if bookmakers and bookmakers[0].get('markets'):
                     for m in bookmakers[0]['markets']:
                        if m['key'] == 'spreads':
                            best_market = m
                            break

            if not best_market: continue

            # Parse Spread Line for Home Team
            # Outcomes: name=HomeTeam, point=-2.5, price=-110
            # We need to find the specific outcome for the Home Team to standardize
            home_outcome = next((o for o in best_market['outcomes'] if o['name'] == home_team), None)
            if not home_outcome: continue
            
            market_spread = home_outcome.get('point')
            if market_spread is None: continue
            
            # Run Prediction
            pred = self.predict(game_id, home_team, away_team, market_spread)
            
            # Edge Calculation
            # fair_spread is typically negative for favorites (e.g. -6.5). 
            # market_spread is also negative for favorites (e.g. -2.5).
            # If fair is -6.5 (we think they win by 6.5) and market is -2.5 (need to win by 2.5),
            # that's a HUGE edge on the favorite.
            
            # Logic: 
            # Edge = abs(Fair - Market)? 
            # If we like Home (-6.5) and Market is -2.5 => Edge 4.0 pts.
            # If we like Home (-1.0) and Market is -2.5 => Value is on AWAY.
            
            # Re-eval based on prediction logic:
            # fair_spread = -6.5 (Home favored by 6.5)
            # market_spread = -2.5
            
            diff = pred['fair_spread'] - market_spread
            # If diff is negative (e.g. -6.5 - (-2.5) = -4.0), it means we think Home is STRONGER (more negative spread).
            # If diff is positive (e.g. -1.0 - (-2.5) = +1.5), we think Home is WEAKER.
            
            # Always show games, determining lean based on diff
            edges.append({
                "game_id": game_id,
                "sport": "NFL",
                "start_time": game.get('commence_time'), 
                "home_team": home_team,
                "away_team": away_team,
                "market": "Spread",
                "bet_on": home_team if diff < 0 else away_team,
                "market_line": market_spread if diff < 0 else (-1 * market_spread if market_spread is not None else 0),
                "fair_line": pred['fair_spread'] if diff < 0 else (-1 * pred['fair_spread']),
                "win_prob": round(pred['win_prob'] if diff < 0 else (1 - pred['win_prob']), 3),
                "edge": round(abs(diff), 1),
                "odds": home_outcome.get('price') if diff < 0 else (next((o for o in best_market['outcomes'] if o['name'] == away_team), home_outcome)).get('price'),
                "book": bookmakers[0]['title'] if bookmakers else 'consensus'
            })

        return edges

    def evaluate(self, predictions: List[Dict[str, Any]]):
        pass
