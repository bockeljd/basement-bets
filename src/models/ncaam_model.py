import sys
import os
import pandas as pd
import requests
import numpy as np
import time

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from src.models.base_model import BaseModel
from src.models.odds_client import OddsAPIClient
from typing import Dict, Any, List

class NCAAMModel(BaseModel):
    """
    NCAAM Predictive Model - Totals (Monte Carlo).
    Source: Sports-Reference (Scraping Advanced Stats).
    """
    
    STATS_URL = "https://www.sports-reference.com/cbb/seasons/men/2026-advanced-school-stats.html"
    
    # Team Mapping Helper (Odds API names are messy for colleges)
    # We will try a fuzzy match or manual map map for major teams later.
    # For now, we assume simple matching (e.g. "Duke" == "Duke").
    
    def __init__(self):
        super().__init__(sport_key="basketball_ncaab")
        self.odds_client = OddsAPIClient()
        self.team_stats = {}
        self.league_avg = {}

    def fetch_data(self):
        """
        Scrape Advanced Stats from Sports-Reference.
        """
        print(f"  [MODEL] Scraped Advanced Stats from {self.STATS_URL}...")
        
        try:
            # Add headers to avoid bot detection
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
            }
            resp = requests.get(self.STATS_URL, headers=headers)
            resp.raise_for_status()
            
            # Parse Tables
            dfs = pd.read_html(resp.text)
            if not dfs:
                print("  [ERROR] No tables found in HTML.")
                return {}
                
            df = dfs[0]
            
            # Clean Data
            # Handle MultiIndex: We specifically want 'Pace', 'ORtg', and 'Opp.' (Points Allowed)
            # The Debug script showed flattened cols include these.
            if isinstance(df.columns, pd.MultiIndex):
                # Flatten
                df.columns = df.columns.map(lambda x: x[1] if "Unnamed" not in x[1] else x[0])
            
            # Remove divider rows
            df = df[df['School'] != 'School']
            
            # Convert to numeric
            cols_to_convert = ['Pace', 'ORtg', 'Opp.', '3PAr', 'ORB%']
            for c in cols_to_convert:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
            
            # Drop NaN
            df = df.dropna(subset=['Pace', 'ORtg', 'Opp.'])
            
            # Calculate DRtg if missing
            # DRtg = (Opp Points / Pace) * 100
            if 'DRtg' not in df.columns and 'Opp.' in df.columns and 'Pace' in df.columns:
                df['DRtg'] = (df['Opp.'] / df['Pace']) * 100
            
            # Recalculate League Avg
            self.league_avg = {
                'Pace': df['Pace'].mean(),
                'ORtg': df['ORtg'].mean(),
                'DRtg': df['DRtg'].mean(),
                '3PAr': df['3PAr'].mean(),
                'ORB%': df['ORB%'].mean()
            }
            print(f"  [STATS] League Averages: Pace={self.league_avg['Pace']:.1f}, ORtg={self.league_avg['ORtg']:.1f}")

            # Store in Dict
            self.team_stats = {}
            for _, row in df.iterrows():
                # Clean Team Name (remove "NCAA" suffix if present)
                team_name = row['School'].replace(" NCAA", "").strip()
                self.team_stats[team_name] = {
                    'Pace': row['Pace'],
                    'ORtg': row['ORtg'],
                    'DRtg': row['DRtg'],
                    '3PAr': row['3PAr'],
                    'ORB%': row['ORB%']
                }
            
            print(f"  [MODEL] Loaded stats for {len(self.team_stats)} schools.")
            return self.team_stats

        except Exception as e:
            print(f"  [ERROR] Failed to fetch data: {e}")
            return {}

    def predict(self, game_id: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Predict Total Points using KenPom-style logic.
        """
        # Fuzzy Match / Name Checks needed here usually.
        # For prototype, we expect exact match or we skip.
        home_stats = self.team_stats.get(home_team)
        away_stats = self.team_stats.get(away_team)
        
        # Try simplified names (e.g. remove "State" -> "St")?
        # For now, just skip if not found.
        if not home_stats:
            # print(f"  [SKIP] Missing stats for {home_team}")
            return None
        if not away_stats:
            # print(f"  [SKIP] Missing stats for {away_team}")
            return None

        # Logic:
        # Projected Pace = (Pace_H - Avg) + (Pace_A - Avg) + Avg
        pace_proj = (home_stats['Pace'] - self.league_avg['Pace']) + \
                    (away_stats['Pace'] - self.league_avg['Pace']) + \
                    self.league_avg['Pace']
        
        # Projected Efficiency
        # Home Off Eff = (Home_ORtg - Avg) + (Away_DRtg - Avg) + Avg
        home_eff = (home_stats['ORtg'] - self.league_avg['ORtg']) + \
                   (away_stats['DRtg'] - self.league_avg['DRtg']) + \
                   self.league_avg['ORtg']
                   
        away_eff = (away_stats['ORtg'] - self.league_avg['ORtg']) + \
                   (home_stats['DRtg'] - self.league_avg['DRtg']) + \
                   self.league_avg['ORtg']
                   
        # Projected Points
        # Points = (Eff / 100) * Pace
        home_pts = (home_eff / 100) * pace_proj
        away_pts = (away_eff / 100) * pace_proj
        
        total_proj = home_pts + away_pts
        
        return {
            "game_id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "fair_total": round(total_proj, 1),
            "pace": round(pace_proj, 1),
            "home_pts": round(home_pts, 1),
            "away_pts": round(away_pts, 1),
            "home_stats": home_stats, # Pass full stats for auditor
            "away_stats": away_stats
        }
    
    def find_edges(self):
        if not self.team_stats:
            self.fetch_data()
            
        print("  [MODEL] Fetching Market Odds (Totals)...")
        # Ensure we ask for 'totals' market
        odds_data = self.odds_client.get_odds(self.sport_key, markets='totals')
        if not odds_data:
            print("  [MODEL] No odds data found.")
            return []

        edges = []
        print(f"  [MODEL] Analyzing {len(odds_data)} games...")
        
        for game in odds_data:
            home = game['home_team']
            away = game['away_team']
            
            # Try to map Odds API names to SR names
            # Simple heuristic: "North Carolina" -> "North Carolina"
            # "State" vs "St" is common mismatch.
            pred = self.predict(game['id'], self._map_name(home), self._map_name(away))
            if not pred: continue
            
            fair = pred['fair_total']
            
            # Get Market Total
            market_total, bet_type = self._get_market_total(game) # Helper to get line + over/under? 
            # Usually Total is a single number (e.g. 145.5). We compare Fair vs Market.
            
            if market_total is None: continue
            
            diff = fair - market_total
            
            # Logic:
            # If Fair (150) > Market (140) -> Edge on OVER. (Diff = +10)
            # If Fair (130) < Market (140) -> Edge on UNDER. (Diff = -10)
            
            # Determine Actionability & Side
            is_actionable = False
            bet_on = "Pass"
            edge_val = diff
            
            if diff > 3.0:
                is_actionable = True
                bet_on = "OVER"
            elif diff < -3.0:
                is_actionable = True
                bet_on = "UNDER"
                edge_val = abs(diff)
            else:
                # Lean
                bet_on = "OVER" if diff > 0 else "UNDER"
                edge_val = abs(diff)

            edges.append({
                "game": f"{away} @ {home}",
                "bet_on": bet_on,
                "market_line": market_total,
                "fair_line": fair,
                "edge": round(edge_val, 1),
                "is_actionable": is_actionable,
                "start_time": game.get('commence_time'),
                "home_team": home, # Needed for auditor lookups
                "away_team": away,
                "home_stats": pred['home_stats'],
                "away_stats": pred['away_stats']
            })
                
        return edges

    def _map_name(self, name):
        """
        Map Odds API name (e.g. "Buffalo Bulls") to SR name (e.g. "Buffalo").
        Logic: Find longest SR key that is a substring of the input name.
        """
        if not self.team_stats:
            return name
            
        # Sort keys by length desc to prevent "Iowa" matching "Iowa State" first
        sorted_keys = sorted(self.team_stats.keys(), key=len, reverse=True)
        
        for key in sorted_keys:
            if key in name:
                return key
                
        # Fallback or specific overrides
        return name

    def _get_market_total(self, game):
        # Average the lines or take DraftKings
        for book in game.get('bookmakers', []):
            if book['key'] in ['draftkings', 'fanduel', 'mgm', 'actionnetwork']:
                for mkt in book.get('markets', []):
                    if mkt['key'] == 'totals':
                        # Usually has outcomes "Over" and "Under" with same 'point'
                        # Return 'point'
                        if len(mkt['outcomes']) > 0:
                            return mkt['outcomes'][0]['point'], "Total"
        return None, None

    def evaluate(self, predictions):
        pass

if __name__ == "__main__":
    model = NCAAMModel()
    edges = model.find_edges()
    print(f"\nFound {len(edges)} edges:")
    for e in edges:
        print(f"{e['game']} | Bet {e['bet_on']} {e['market_line']} (Fair: {e['fair_line']}) | Edge: {e['edge']}")
