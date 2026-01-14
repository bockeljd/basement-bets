import sys
import os
import pandas as pd
import requests
import io
import numpy as np
import math
from typing import Dict, Any, List

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from src.models.base_model import BaseModel
from src.models.odds_client import OddsAPIClient

def poisson_pmf(k, mu):
    return (mu**k * math.exp(-mu)) / math.factorial(k)

class EPLModel(BaseModel):
    """
    EPL Predictive Model - Moneyline (Poisson Distribution).
    Source: football-data.co.uk (CSV).
    Trigger: >5% Edge.
    """
    
    # CSV URL for current season (2025/2026 -> 2425 in their format usually, but checking URL from task)
    # user confirmed 2425/E0.csv exists.
    STATS_URL = "https://www.football-data.co.uk/mmz4281/2425/E0.csv"
    
    # Mapping: CSV Name -> Odds API Name
    TEAM_MAP = {
        'Man United': 'Manchester United',
        'Man City': 'Manchester City',
        'Newcastle': 'Newcastle United',
        "Nott'm Forest": 'Nottingham Forest',
        'Tottenham': 'Tottenham Hotspur',
        'West Ham': 'West Ham United',
        'Wolves': 'Wolverhampton Wanderers',
        'Brighton': 'Brighton and Hove Albion',
        'Leicester': 'Leicester City',
        'Ipswich': 'Ipswich Town',
        # Others usually match (Liverpool, Chelsea, Arsenal, Everton, etc.)
    }

    def __init__(self):
        super().__init__(sport_key="soccer_epl")
        self.odds_client = OddsAPIClient()
        self.team_stats = {}
        self.league_stats = {}

    def fetch_data(self):
        """
        Fetch and parse CSV data from football-data.co.uk.
        """
        print(f"  [MODEL] Fetching stats from {self.STATS_URL}...")
        
        try:
            # Fetch with requests to handle headers/SSL better
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
            }
            resp = requests.get(self.STATS_URL, headers=headers, verify=False) # verify=False to avoid local SSL cert issues
            resp.raise_for_status()
            
            # Read into Pandas
            df = pd.read_csv(io.StringIO(resp.text))
            
            # Filter relevant columns: HomeTeam, AwayTeam, FTHG, FTAG
            required_cols = ['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
            if not all(col in df.columns for col in required_cols):
                print("  [ERROR] CSV missing required columns.")
                return {}
            
            # Calculate metrics
            # We need Average Goals Scored per Game for Home and Away
            # Ideally split by Home/Away form, but a global attack/defense metric is often more robust with small sample sizes early season.
            # Let's do simple global Attack/Defense strength first.
            
            # 1. Aggregate Goals Scored and Conceded by Team
            teams = pd.concat([df['HomeTeam'], df['AwayTeam']]).unique()
            stats = {team: {'scored': 0, 'conceded': 0, 'games': 0} for team in teams}
            
            for _, row in df.iterrows():
                home = row['HomeTeam']
                away = row['AwayTeam']
                hg = row['FTHG']
                ag = row['FTAG']
                
                if pd.isna(hg) or pd.isna(ag): continue
                
                stats[home]['scored'] += hg
                stats[home]['conceded'] += ag
                stats[home]['games'] += 1
                
                stats[away]['scored'] += ag
                stats[away]['conceded'] += hg
                stats[away]['games'] += 1
                
            # 2. Calculate League Averages
            total_goals = sum(s['scored'] for s in stats.values())
            total_games = sum(s['games'] for s in stats.values())
            
            if total_games == 0:
                print("  [ERROR] No games played in data.")
                return {}
            
            avg_goals_per_game = total_goals / total_games 
            
            self.league_stats = {
                'avg_goals': avg_goals_per_game
            }
            
            # 3. Calculate Team Strengths
            # Att Str = (Goals Scored / Games) / League Avg
            # Def Str = (Goals Conceded / Games) / League Avg
            
            self.team_stats = {}
            for team, data in stats.items():
                if data['games'] == 0: continue
                
                avg_scored = data['scored'] / data['games']
                avg_conceded = data['conceded'] / data['games']
                
                att_strength = avg_scored / avg_goals_per_game
                def_strength = avg_conceded / avg_goals_per_game
                
                # Map Name
                mapped_name = self.TEAM_MAP.get(team, team)
                
                self.team_stats[mapped_name] = {
                    'att': att_strength,
                    'def': def_strength
                }
                
            print(f"  [STATS] League Avg Goals: {avg_goals_per_game:.2f}")
            print(f"  [MODEL] Loaded stats for {len(self.team_stats)} teams.")
            return self.team_stats

        except Exception as e:
            print(f"  [ERROR] Failed to fetch/parse CSV: {e}")
            return {}

    def predict(self, game_id: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Calculate Win Probs using Poisson.
        """
        home_stats = self.team_stats.get(home_team)
        away_stats = self.team_stats.get(away_team)
        
        if not home_stats or not away_stats:
            return None
            
        league_avg = self.league_stats.get('avg_goals', 1.5)
        
        # Calculate Expected Goals for this match
        # Home Exp = Home Att * Away Def * League Avg
        home_exp = home_stats['att'] * away_stats['def'] * league_avg
        away_exp = away_stats['att'] * home_stats['def'] * league_avg
        
        # Adjust for Home Field Advantage (approx +15% scoring for home team is valid heuristic)
        home_exp *= 1.15 
        
        # Poisson Simulation
        max_goals = 6
        probs = np.zeros((max_goals, max_goals))
        
        for i in range(max_goals):
            for j in range(max_goals):
                prob_h = poisson_pmf(i, home_exp)
                prob_a = poisson_pmf(j, away_exp)
                probs[i][j] = prob_h * prob_a
                
        # Sum Probs
        prob_home_win = np.sum(np.tril(probs, -1)) # Lower triangle
        prob_draw = np.trace(probs) # Diagonal
        prob_away_win = np.sum(np.triu(probs, 1)) # Upper triangle
        
        # Convert to Fair Odds (Decimal)
        fair_odds_h = 1 / prob_home_win if prob_home_win > 0 else 999
        fair_odds_d = 1 / prob_draw if prob_draw > 0 else 999
        fair_odds_a = 1 / prob_away_win if prob_away_win > 0 else 999
        
        return {
            "game_id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "probs": {
                "home": round(prob_home_win, 3),
                "draw": round(prob_draw, 3),
                "away": round(prob_away_win, 3)
            },
            "fair_odds": {
                "home": round(fair_odds_h, 2),
                "draw": round(fair_odds_d, 2),
                "away": round(fair_odds_a, 2)
            }
        }
    
    def find_edges(self):
        if not self.team_stats:
            self.fetch_data()
            
        print("  [MODEL] Fetching Market Odds (H2H)...")
        odds_data = self.odds_client.get_odds(self.sport_key, markets='h2h', odds_format='decimal')
        if not odds_data:
            print("  [MODEL] No odds data found.")
            return []

        edges = []
        print(f"  [MODEL] Analyzing {len(odds_data)} games...")
        
        for game in odds_data:
            home = game['home_team']
            away = game['away_team']
            
            # Determine Actionability & Side (consistent with other models)
            pred = self.predict(game['id'], home, away)
            if not pred: continue
            
            market_odds = self._get_market_odds(game) # Returns dict {home, draw, away}
            fair_odds = pred['fair_odds']
            probs = pred['probs']
            
            if not market_odds: continue
            
            # Check for best edge
            best_edge = None
            best_ev = -float('inf')
            best_outcome = None
            
            for outcome in ['home', 'draw', 'away']:
                m_odd = market_odds.get(outcome)
                prob = probs.get(outcome)
                
                if m_odd and prob:
                    ev = (prob * m_odd) - 1
                    if ev > best_ev:
                        best_ev = ev
                        best_edge = {
                            "outcome": outcome,
                            "ev": ev,
                            "market_odd": m_odd,
                            "fair_odd": fair_odds.get(outcome)
                        }

            if best_edge:
                is_actionable = best_edge['ev'] > 0.05 # >5% EV
                
                bet_on_str = f"{best_edge['outcome'].upper()} ({home if best_edge['outcome']=='home' else (away if best_edge['outcome']=='away' else 'Draw')})"
                
                edges.append({
                    "game": f"{home} vs {away}",
                    "bet_on": bet_on_str,
                    "market_line": best_edge['market_odd'],
                    "fair_line": best_edge['fair_odd'],
                    "edge": round(best_edge['ev'] * 100, 1),
                    "is_actionable": is_actionable,
                    "market": "Moneyline",
                    "logic": f"EV: {round(best_edge['ev']*100,1)}%",
                    "sport": "EPL",
                    "start_time": game.get('commence_time')
                })
                        
        return edges

    def _get_market_odds(self, game):
        # Return best available decimal odds
        best_odds = {'home': 0, 'draw': 0, 'away': 0}
        
        for book in game.get('bookmakers', []):
            if book['key'] in ['draftkings', 'fanduel', 'mgm', 'actionnetwork']:
                for mkt in book.get('markets', []):
                    if mkt['key'] == 'h2h':
                        for out in mkt.get('outcomes', []):
                            price = out['price']
                            name = out['name']
                            
                            if name == game['home_team']:
                                best_odds['home'] = max(best_odds['home'], price)
                            elif name == game['away_team']:
                                best_odds['away'] = max(best_odds['away'], price)
                            elif name == 'Draw':
                                best_odds['draw'] = max(best_odds['draw'], price)
        
        if best_odds['home'] > 0:
            return best_odds
        return None

    def evaluate(self, predictions):
        pass

if __name__ == "__main__":
    model = EPLModel()
    edges = model.find_edges()
    print(f"\\nFound {len(edges)} edges:")
    for e in edges:
        if e['is_actionable']:
            status = "[ACTION]"
        else:
            status = "[LEAN]"
        print(f"{status} {e['game']} | {e['bet_on']} | Market: {e['market_line']} (Fair: {e['fair_line']}) | Edge: +{e['edge']}%")
