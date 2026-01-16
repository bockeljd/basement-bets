import pandas as pd
import numpy as np
from typing import Dict, Any, List
from src.models.base_model import BaseModel

class NCAAMModel(BaseModel):
    def __init__(self):
        super().__init__(sport_key="basketball_ncaab")
        self.team_stats = {} # Map of team -> {adj_eff, tempo}
        self.league_avg_eff = 105.0
        self.league_avg_tempo = 68.5

    def fetch_data(self):
        """
        Fetch dynamic efficiency ratings from BartTorvik.
        """
        from src.services.barttorvik import BartTorvikClient
        client = BartTorvikClient()
        ratings = client.get_efficiency_ratings(year=2026)
        
        # Normalize keys to match Model expectation (eff_off, eff_def)
        self.team_stats = {}
        if ratings:
            for team, stats in ratings.items():
                self.team_stats[team] = {
                    "eff_off": stats.get('off_rating'),
                    "eff_def": stats.get('def_rating'),
                    "tempo": stats.get('tempo')
                }
        
        # Fallback if empty (shouldn't happen with live internet)
        if not self.team_stats:
            print("[NCAAM] Warning: Using fallback MVP stats.")
            self.team_stats = {
             "Houston": {"eff_off": 118.5, "eff_def": 87.0, "tempo": 63.5},
             # Add a few just in case
            }

    def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """
        Retrieve stats with fuzzy matching for team names.
        """
        if not self.team_stats:
            self.fetch_data()
            
        # 1. Exact Match
        if team_name in self.team_stats:
            return self.team_stats[team_name]
            
        # 2. Fuzzy / Common variations
        # Torvik uses full names "Connecticut", OddsAPI might use "UConn"
        # OddsAPI: "North Carolina", Torvik: "North Carolina"
        # OddsAPI: "Miami (FL)", Torvik: "Miami FL"
        
        normalized_input = team_name.lower().replace('.', '').replace(' st', ' state').replace(' (fl)', '').replace(' u', '')
        
        best_match = None
        best_score = 0
        
        for k, v in self.team_stats.items():
            norm_k = k.lower().replace('.', '').replace(' st', ' state')
            
            # Substring match
            if normalized_input in norm_k or norm_k in normalized_input:
                 return v
                 
            # Specific Overrides
            if "uconn" in normalized_input and "connecticut" in norm_k: return v
            if "mississippi" in normalized_input and "ole miss" in norm_k: return v
            
        # Default Logic
        return {"eff_off": self.league_avg_eff, "eff_def": self.league_avg_eff, "tempo": self.league_avg_tempo}

    def predict(self, game_id: str, home_team: str, away_team: str, market_total: float = 0) -> Dict[str, Any]:
        """
        KenPom Style Total Prediction:
        Possessions = (Home Tempo * Away Tempo) / League Avg Tempo
        Home Points = (Home Off Eff * Away Def Eff / League Avg Eff) * (Possessions / 100)
        Away Points = (Away Off Eff * Home Def Eff / League Avg Eff) * (Possessions / 100)
        """
        if not self.team_stats:
            self.fetch_data()

        h = self.get_team_stats(home_team)
        a = self.get_team_stats(away_team)
        
        poss = (h['tempo'] * a['tempo']) / self.league_avg_tempo
        
        h_pts = (h['eff_off'] * a['eff_def'] / self.league_avg_eff) * (poss / 100)
        a_pts = (a['eff_off'] * h['eff_def'] / self.league_avg_eff) * (poss / 100)
        
        fair_total = h_pts + a_pts
        
        # Prob(Total > Market)
        # NCAA Totals have std dev ~11.5
        from scipy.stats import norm
        std_dev = 11.5
        win_prob_over = 1 - norm.cdf(market_total, loc=fair_total, scale=std_dev)
        
        return {
            "game_id": game_id,
            "fair_total": round(fair_total * 2) / 2,
            "win_prob": win_prob_over,
            "edge": win_prob_over - 0.524, # -110 break even
            "model_version": "2024-01-14-ncaam-v1"
        }

    def find_edges(self):
        """
        Fetch live odds and compare with model predictions to find edges.
        """
        from src.models.odds_client import OddsAPIClient
        client = OddsAPIClient()

        # Load Conference Filter
        import json
        import os
        try:
            # Construct absolute path to ensure loading works
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, 'data', 'ncaam_conferences.json')
            
            with open(config_path, 'r') as f:
                conf_data = json.load(f)
                target_teams = set()
                for conf, teams in conf_data.items():
                    target_teams.update([t.lower() for t in teams])
            print(f"[DEBUG] Loaded {len(target_teams)} target teams from {config_path}")
        except Exception as e:
            print(f"[NCAAM] Error loading conference filter: {e}")
            target_teams = None
            
        # Helper for fuzzy matching against whitelist
        def is_target_team(team_name):
            if not target_teams: return True # Fail open if no config
            t_norm = team_name.lower()
            if t_norm in target_teams: return True
            # Partial match check
            for target in target_teams: 
                # STRICTER MATCHING:
                if target in t_norm:
                     return True
            return False
        
        # Get live odds for NCAAB
        odds = client.get_odds("basketball_ncaab", regions="us", markets="totals")
        
        edges = []
        for game in odds:
            game_id = game.get('id')
            home_team = game.get('home_team')
            away_team = game.get('away_team')
            
            if target_teams:
                if not (is_target_team(home_team) or is_target_team(away_team)):
                    # print(f"[NCAAM] Skipping non-target matchup: {away} @ {home}") 
                    continue
                else:
                    # print(f"[NCAAM] Processing target matchup: {away} @ {home}")
                    pass
            
            game_id = game.get('id')
            
            # Find Totals Market
            # OddsAPI structure: bookmakers -> markets -> outcomes
            # We want consensus or specific book? Let's take 'DraftKings' or first available.
            
            best_market = None
            bookmakers = game.get('bookmakers', [])
            
            # Target Books precedence
            target_books = ['draftkings', 'fanduel', 'betmgm']
            
            for book in bookmakers:
                if book['key'] in target_books:
                    for m in book['markets']:
                        if m['key'] == 'totals':
                            best_market = m
                            break
                if best_market: break
                
            if not best_market:
                # Fallback to any book
                if bookmakers and bookmakers[0].get('markets'):
                     for m in bookmakers[0]['markets']:
                        if m['key'] == 'totals':
                            best_market = m
                            break
                            
            if not best_market or not best_market.get('outcomes'):
                continue
                
            # Parse Market Line
            # Outcomes: name=Over, point=140.5, price=-110
            over = next((o for o in best_market['outcomes'] if o['name'] == 'Over'), None)
            if not over: continue
            
            market_total = over.get('point')
            if not market_total: continue
            
            # Run Prediction
            pred = self.predict(game_id, home_team, away_team, market_total)
            
            # Line Difference (Point Edge)
            line_diff = pred['fair_total'] - market_total
            
            # Probabilities for risk management (EV/Kelly)
            prob_val = round(pred['win_prob'], 3)
            
            # Threshold for actionability (e.g. 2 points)
            if line_diff >= 1.0: 
                edges.append({
                    "game_id": game_id,
                    "sport": "NCAAM",
                    "start_time": game.get('commence_time'), 
                    "home_team": home_team,
                    "away_team": away_team,
                    "market": "Total",
                    "bet_on": "OVER",
                    "market_line": market_total,
                    "fair_line": pred['fair_total'],
                    "win_prob": prob_val,
                    "edge": round(line_diff, 1), # Point Edge
                    "odds": over.get('price'),
                    "book": bookmakers[0]['title'] 
                })
            elif line_diff <= -1.0: 
                prob_under = 1 - pred['win_prob']
                edges.append({
                    "game_id": game_id,
                    "sport": "NCAAM",
                    "start_time": game.get('commence_time'),
                    "home_team": home_team,
                    "away_team": away_team,
                    "market": "Total",
                    "bet_on": "UNDER",
                    "market_line": market_total,
                    "fair_line": pred['fair_total'],
                    "win_prob": round(prob_under, 3),
                    "edge": round(abs(line_diff), 1), # Point Edge (positive value)
                    "odds": over.get('price'),
                    "book": bookmakers[0]['title']
                })
                    
        return edges

    def evaluate(self, predictions: List[Dict[str, Any]]):
        pass
