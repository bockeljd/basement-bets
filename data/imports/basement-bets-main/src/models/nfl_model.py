import pandas as pd
import numpy as np
from typing import Dict, Any, List
from src.models.base_model import BaseModel

class NFLModel(BaseModel):
    def __init__(self):
        super().__init__(sport_key="americanfootball_nfl")
        self.team_ratings = {} # Map of team -> rating

    def fetch_data(self):
        """
        In a real scenario, this would fetch from a database or API.
        For MVP, we use a simple static map of current power ratings (0-100 scale).
        """
        self.team_ratings = {
            "Kansas City Chiefs": 92.5,
            "San Francisco 49ers": 91.0,
            "Baltimore Ravens": 89.5,
            "Buffalo Bills": 88.0,
            "Detroit Lions": 87.5,
            "Dallas Cowboys": 86.0,
            "Philadelphia Eagles": 85.5,
            "Miami Dolphins": 84.0,
            "Houston Texans": 83.5,
            "Cleveland Browns": 82.0,
            "Los Angeles Rams": 81.5,
            "Green Bay Packers": 81.0,
            "Tampa Bay Buccaneers": 79.5,
            "Jacksonville Jaguars": 78.0,
            "Seattle Seahawks": 77.5,
            "Cincinnati Bengals": 77.0,
            "Pittsburgh Steelers": 76.5,
            "Indianapolis Colts": 75.0,
            "Minnesota Vikings": 74.5,
            "Chicago Bears": 73.0,
            "Atlanta Falcons": 72.5,
            "New Orleans Saints": 72.0,
            "Denver Broncos": 71.5,
            "Las Vegas Raiders": 70.0,
            "New York Jets": 69.5,
            "Tennessee Titans": 68.0,
            "New York Giants": 67.5,
            "Washington Commanders": 66.0,
            "Arizona Cardinals": 65.5,
            "New England Patriots": 64.0,
            "Carolina Panthers": 62.0,
            "Los Angeles Chargers": 70.0
        }

    def predict(self, game_id: str, home_team: str, away_team: str, market_spread: float = 0) -> Dict[str, Any]:
        """
        Simplistic NFL Spread Model:
        Predicted Margin = (Home Rating - Away Rating) + Home Field Advantage (approx 1.5 - 2.0 pts)
        """
        if not self.team_ratings:
            self.fetch_data()

        h_rate = self.team_ratings.get(home_team, 75.0)
        a_rate = self.team_ratings.get(away_team, 75.0)
        
        home_field = 1.8 
        raw_margin = (h_rate - a_rate) + home_field
        
        # Convert Margin to Spread Win Prob
        std_dev = 13.5
        from scipy.stats import norm
        
        # Prob cover: Margin vs -Spread (since spread is usually -7.5 for favorite)
        win_prob_cover = 1 - norm.cdf(-market_spread, loc=raw_margin, scale=std_dev)
        
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
            
            # Threshold
            threshold = 1.5 
            
            if diff <= -threshold:
                # We show Home is better than market thinks
                edges.append({
                    "game_id": game_id,
                    "sport": "NFL",
                    "start_time": game.get('commence_time'), 
                    "home_team": home_team,
                    "away_team": away_team,
                    "market": "Spread",
                    "bet_on": home_team, # Betting Home Cover
                    "market_line": market_spread,
                    "fair_line": pred['fair_spread'],
                    "win_prob": round(pred['win_prob'], 3),
                    "edge": round(abs(diff), 1),
                    "odds": home_outcome.get('price'),
                    "book": bookmakers[0]['title']
                })
            elif diff >= threshold:
                # Market is too high on Home, bet Away
                # Away Line is roughly -1 * Market Line (usually)
                away_outcome = next((o for o in best_market['outcomes'] if o['name'] == away_team), None)
                if away_outcome:
                    edges.append({
                        "game_id": game_id,
                        "sport": "NFL",
                        "start_time": game.get('commence_time'),
                        "home_team": home_team,
                        "away_team": away_team,
                        "market": "Spread",
                        "bet_on": away_team, # Betting Away Cover
                        "market_line": away_outcome.get('point'),
                        "fair_line": -1 * pred['fair_spread'], # Invert for Away perspective
                        "win_prob": round(1 - pred['win_prob'], 3), # Approx flip
                        "edge": round(abs(diff), 1),
                        "odds": away_outcome.get('price'),
                        "book": bookmakers[0]['title']
                    })

        return edges

    def evaluate(self, predictions: List[Dict[str, Any]]):
        pass
