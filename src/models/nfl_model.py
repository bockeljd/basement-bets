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
from typing import Dict, Any, List

class NFLModel(BaseModel):
    """
    NFL Predictive Model - Real Data Version.
    Source: nfl_data_py (Play-by-Play EPA).
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

    SCALE_FACTOR = 15.0 
    HFA = 2.0 

    def __init__(self):
        super().__init__(sport_key="americanfootball_nfl")
        self.odds_client = OddsAPIClient()
        self.team_stats = {}

    def fetch_data(self):
        """
        Fetch real-world play-by-play data and calculate Team EPA.
        """
        print("  [MODEL] Loading NFL Play-by-Play Data (2025 Local)...")
        # Load local parquet (Manual Download)
        try:
            pbp = pd.read_parquet(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'play_by_play_2025.parquet'))
        except Exception as e:
            print(f"  [ERROR] Failed to load local data: {e}")
            return {}
        
        # Filter: Plays with EPA, Regular/Post Season
        mask = (pbp['epa'].notna()) & (pbp['posteam'].notna())
        df = pbp[mask]
        
        print(f"  [MODEL] Processing {len(df)} plays...")
        
        # Aggregate EPA by Team (Mean EPA/Play)
        # We can also filter for garbage time later, but keep it simple for now.
        team_epa = df.groupby('posteam')['epa'].mean()
        
        # Store in self.team_stats with Odds API Names
        self.team_stats = {}
        for abbr, epa in team_epa.items():
            full_name = self.TEAM_MAP.get(abbr)
            if full_name:
                self.team_stats[full_name] = round(epa, 3)
            else:
                print(f"  [WARN] Unknown team abbreviation: {abbr}")
                
        # Debug Output
        # top_5 = sorted(self.team_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        # print(f"  [STATS] Top 5 Offenses (EPA/Play): {top_5}")
        
        return self.team_stats

    def predict(self, game_id: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Predict Fair Spread using Real EPA.
        """
        home_epa = self.team_stats.get(home_team)
        away_epa = self.team_stats.get(away_team)
        
        if home_epa is None or away_epa is None:
            # print(f"  [SKIP] Missing data for {home_team} or {away_team}")
            return None

        # Logic: (Away - Home) * Scale - HFA?
        # Standard: Spread is Points needed to equalize.
        # If Home is Better (Higher EPA), Spread should be Negative.
        # Diff = Away - Home. (-0.1 - 0.1 = -0.2).
        # Fair = -0.2 * 15 = -3.0.
        # -3.0 - 2.0(HFA) = -5.0.
        
        raw_diff = away_epa - home_epa
        fair_spread = (raw_diff * self.SCALE_FACTOR) - self.HFA

        return {
            "game_id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "fair_spread": round(fair_spread, 1),
            "home_epa": home_epa,
            "away_epa": away_epa
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
            
            if diff > 1.5:
                is_actionable = True
                bet_on = home
            elif diff < -1.5:
                is_actionable = True
                bet_on = away
                edge_val = abs(diff)
            else:
                # Lean
                bet_on = home if diff > 0 else away
                edge_val = abs(diff)

            edges.append({
                "game": f"{away} @ {home}",
                "bet_on": bet_on,
                "market_spread": market_spread,
                "fair_spread": fair_spread,
                "edge": round(edge_val, 1),
                "is_actionable": is_actionable,
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
        print(f"Bet {e['bet_on']} ({e['market_spread']}) vs Fair ({e['fair_spread']}) | Edge: {e['edge']} pts")
