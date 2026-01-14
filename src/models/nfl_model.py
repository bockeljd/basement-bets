import sys
import os
import pandas as pd
import ssl

# Mac/Python SSL Hack for nfl_data_py
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

try:
    import nfl_data_py as nfl
except ImportError:
    print("Warning: nfl_data_py not found. Install with: pip install nfl_data_py")
    nfl = None

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from src.models.base_model import BaseModel
from src.models.odds_client import OddsAPIClient
from src.models.monte_carlo import MonteCarloEngine
from typing import Dict, Any, List

class NFLModel(BaseModel):
    """
    NFL Predictive Model - Real Data Version.
    Source: nfl_data_py (Play-by-Play EPA).
    Uses Monte Carlo Simulation for "Chaos Engine" logic.
    """
    
    # Mapping: nfl_data_py (Abbr) -> Odds API (Full Name)
    TEAM_MAP = {
        'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
        'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns',
        'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
        'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars', 'KC': 'Kansas City Chiefs',
        'LA': 'Los Angeles Rams', 'LAC': 'Los Angeles Chargers', 'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
        'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
        'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks',
        'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'
    }

    # Reverse Map for lookups
    REVERSE_MAP = {v: k for k, v in TEAM_MAP.items()}

    def __init__(self):
        super().__init__(sport_key="americanfootball_nfl")
        self.odds_client = OddsAPIClient()
        self.mc_engine = MonteCarloEngine(simulations=5000)
        self.team_stats = {}

    def fetch_data(self):
        """
        Fetch real-world play-by-play data and calculate Team EPA and Volatility.
        """
        print("  [MODEL] Loading NFL Play-by-Play Data (2025 Local)...")
        # Load local parquet (Manual Download)
        try:
            # Try 2024 if 2025 fails, or just assume the file exists as per setup
            pbp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'play_by_play_2025.parquet')
            if not os.path.exists(pbp_path):
                 pbp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'play_by_play_2024.parquet')
            
            pbp = pd.read_parquet(pbp_path)
        except Exception as e:
            print(f"  [ERROR] Failed to load local data: {e}")
            return {}
        
        # Filter: Plays with EPA, Regular/Post Season
        mask = (pbp['epa'].notna()) & (pbp['posteam'].notna())
        df = pbp[mask]
        
        print(f"  [MODEL] Processing {len(df)} plays...")
        
        # Aggregate EPA by Team (Mean & Std Dev for Volatility)
        stats = df.groupby('posteam')['epa'].agg(['mean', 'std'])
        
        # Store in self.team_stats with Odds API Names
        self.team_stats = {}
        for abbr, row in stats.iterrows():
            full_name = self.TEAM_MAP.get(abbr)
            if full_name:
                self.team_stats[full_name] = {
                    'epa': round(row['mean'], 3),
                    # Heuristic Volatility: Scale EPA std (~0.7) to Match std (~10.5)
                    'volatility': round(row['std'] * 15.0, 2)
                }
                
        # Debug Output
        top_5 = sorted(self.team_stats.items(), key=lambda x: x[1]['epa'], reverse=True)[:5]
        print(f"  [STATS] Top 5 Offenses (EPA/Play): {[(k, v['epa']) for k,v in top_5]}")
        
        return self.team_stats

    def predict(self, game_id: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Predict Fair Spread using Monte Carlo Interaction.
        """
        h_stats = self.team_stats.get(home_team)
        a_stats = self.team_stats.get(away_team)
        
        if not h_stats or not a_stats:
            return None

        # CALCULATE PROJECTED SCORE (INTERACTION)
        # Using a base NFL score of 21.5
        # Simplified EPA-to-Points projection for Monte Carlo
        h_proj = 21.5 + ((h_stats['epa'] - a_stats['epa']) * 30)
        a_proj = 21.5 + ((a_stats['epa'] - h_stats['epa']) * 30)
        
        # DELEGATE TO CHAOS ENGINE
        sim_result = self.mc_engine.simulate_game(
            home_proj=h_proj, home_vol=h_stats['volatility'],
            away_proj=a_proj, away_vol=a_stats['volatility']
        )
        
        return {
            "game_id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "fair_spread": sim_result.fair_spread,
            "fair_total": sim_result.fair_total,
            "win_prob": sim_result.home_win_pct,
            "edge_detected": sim_result.edge_detected,
            "volatility_edge": sim_result.volatility_edge,
            "home_stats": h_stats,
            "away_stats": a_stats
        }
    
    def find_edges(self):
        # 1. Load Data
        if not self.team_stats:
            self.fetch_data()
        
        # 2. Get Odds
        print("  [MODEL] Fetching Market Odds...")
        odds_data = self.odds_client.get_odds(self.sport_key)
        if not odds_data:
            print("  [MODEL] No odds data found.")
            return []

        edges = []
        print(f"  [MODEL] Analyzing {len(odds_data)} games...")
        
        for game in odds_data:
            home = game['home_team']
            away = game['away_team']
            game_id = game['id']
            
            # Predict
            prediction = self.predict(game_id, home, away)
            if not prediction: continue
            
            fair_spread = prediction['fair_spread']
            
            # Get Market Spread
            market_spread = self._get_market_spread(game)
            if market_spread is None: continue
            
            # Compare
            diff = market_spread - fair_spread
            
            # Determine Actionability & Side
            is_actionable = False
            bet_on = "Pass"
            edge_val = diff
            
            # Edge Threshold: > 3.0 points (Volatility safe)
            if diff > 3.0:
                is_actionable = True
                bet_on = home # Market (-3) > Fair (-7). Edge Home. Or Market (+7) > Fair (+3).
            elif diff < -3.0:
                is_actionable = True
                bet_on = away
                edge_val = abs(diff)
            else:
                bet_on = home if diff > 0 else away
                edge_val = abs(diff)

            edges.append({
                "game": f"{away} @ {home}",
                "bet_on": bet_on,
                "market_spread": market_spread,
                "fair_spread": fair_spread,
                "win_prob": prediction['win_prob'],
                "edge": round(edge_val, 1),
                "is_actionable": is_actionable or prediction['edge_detected'],
                "start_time": game.get('commence_time')
            })
                
        return edges

    def _get_market_spread(self, game):
        for book in game.get('bookmakers', []):
            if book['key'] in ['draftkings', 'fanduel', 'mgm', 'actionnetwork']:
                for mkt in book.get('markets', []):
                    if mkt['key'] == 'spreads':
                        for out in mkt.get('outcomes', []):
                            if out['name'] == game['home_team']:
                                return out['point']
        return None

    def evaluate(self, predictions: List[Dict[str, Any]]):
        pass

if __name__ == "__main__":
    model = NFLModel()
    edges = model.find_edges()
    print(f"\nFound {len(edges)} edges:")
    for e in edges:
        action = " [BET]" if e['is_actionable'] else ""
        print(f"Bet {e['bet_on']} ({e['market_spread']}) vs Fair ({e['fair_spread']}) | Edge: {e['edge']} pts{action}")
