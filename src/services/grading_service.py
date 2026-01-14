import os
import requests
import json
import sqlite3
from datetime import datetime, timedelta
import sys

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import fetch_model_history, update_model_prediction_result
from models.odds_client import OddsAPIClient

# Load env variables if not already loaded
from dotenv import load_dotenv
load_dotenv()

class GradingService:
    def __init__(self):
        self.client = OddsAPIClient()


    def grade_predictions(self):
        """
        Main method to Grade 'Pending' predictions.
        """
        predictions = fetch_model_history()
        pending = [p for p in predictions if p['result'] == 'Pending']
        
        print(f"[GRADING] Found {len(pending)} pending predictions.")
        
        if not pending:
            return {"status": "No pending bets to grade"}

        graded_count = 0
        
        # Group by sport to minimize API calls
        by_sport = {}
        for p in pending:
            s = p['sport']
            if s not in by_sport: by_sport[s] = []
            by_sport[s].append(p)
            
        for sport, preds in by_sport.items():
            print(f"[GRADING] Processing {len(preds)} bets for {sport}...")
            
            # Map sport name to API key (simple mapping)
            sport_key = self._map_sport_to_key(sport)
            if not sport_key:
                print(f"  [SKIP] Unknown sport key for {sport}")
                continue
                
            # Fetch scores (Last 3 days should cover recent pending bets)
            scores = self._fetch_scores(sport_key, days=3)
            
            for p in preds:
                result = self._evaluate_prediction(p, scores)
                if result and result != 'Pending':
                    update_model_prediction_result(p['id'], result)
                    graded_count += 1
                    
        return {"status": "Success", "graded": graded_count}

    def _map_sport_to_key(self, sport):
        # Extend this mapping as needed
        mapping = {
            'NFL': 'americanfootball_nfl',
            'NCAAF': 'americanfootball_ncaaf',
            'NCAAM': 'basketball_ncaab', # Or 'basketball_ncaab_totals'? Standard key is basketball_ncaab
            'NBA': 'basketball_nba',
            'EPL': 'soccer_epl'
        }
        return mapping.get(sport)

    def _fetch_scores(self, sport_key, days=3):
        return self.client.get_scores(sport_key, days_from=days)


    def _evaluate_prediction(self, pred, scores):
        """
        Compare prediction against actual scores.
        """
        game_id = pred['game_id'] 
        # Note: game_id in our DB might not match exactly if IDs change, 
        # but OddsAPI IDs are usually stable for a short time. 
        # Fallback: Match by Team Names + Date.
        
        match = None
        for s in scores:
            if s['id'] == game_id:
                match = s
                break
        
        # Fallback Matcher (if ID mismatch)
        if not match:
             # Implementation dependent: Fuzzy match names?
             # For now, trust ID or skip.
             pass
             
        if not match or not match.get('completed'):
            return 'Pending'
            
        # Get Scores
        # scores list inside match dict usually looks like:
        # "scores": [{"name": "HomeTeam", "score": "21"}, ...]
        # Actually OddsAPI 'scores' endpoint structure:
        # list of games. Each game has 'scores': [{name:..., score:...}, {name:..., score:...}] (sometimes null if not started)
        
        final_scores = match.get('scores')
        if not final_scores: return 'Pending'
        
        home_team = match['home_team']
        away_team = match['away_team']
        
        home_score = 0
        away_score = 0
        
        for fs in final_scores:
            if fs['name'] == home_team:
                home_score = int(fs['score'])
            elif fs['name'] == away_team:
                away_score = int(fs['score'])
                
        # Evaluate Logic based on Market Type
        bet_on = pred['bet_on'] 
        # bet_on string examples: "OVER (Pass)", "KC -3.5", "BUF -150", "HOME (Arsenal)"
        
        # 1. Moneyline
        if "HOME" in bet_on and "(" in bet_on: # e.g. "HOME (Arsenal)"
            # EPL format logic
            if home_score > away_score: return 'Win'
            elif home_score == away_score: return 'Loss' # Draw is loss for ML
            else: return 'Loss'
        elif "AWAY" in bet_on and "(" in bet_on:
             if away_score > home_score: return 'Win'
             else: return 'Loss'
        elif "DRAW" in bet_on:
             if home_score == away_score: return 'Win'
             else: return 'Loss'
             
        # 2. Spreads / Totals (NFL/NCAAM)
        # We need to parse valid bet_on strings.
        # "OVER"
        if "OVER" in bet_on:
            total_score = home_score + away_score
            line = pred['market_line'] # numeric
            if total_score > line: return 'Win'
            elif total_score < line: return 'Loss'
            else: return 'Push'
            
        if "UNDER" in bet_on:
            total_score = home_score + away_score
            line = pred['market_line']
            if total_score < line: return 'Win'
            elif total_score > line: return 'Loss'
            else: return 'Push'
            
        # Spreads: "TeamName -Line" or just "TeamName" if ML?
        # My current spread logic stores bet_on as "TeamName" for spreads? 
        # Let's check NFLModel logic: `bet_on` = home (team name)
        # So it's just the team name. The spread is `market_line`.
        
        # If bet_on matches Home Team
        if bet_on == home_team:
            # Spread: Home Score + Spread vs Away Score
            # Spread is usually stored as negative for favorites (e.g. -3.5)
            # So: (Home + Spread) > Away = Win.
            # wait, `market_spread` in DB is stored as what?
            spread = pred['market_line']
            # If spread is -3.5, Home needs to win by 4.
            if (home_score + spread) > away_score: return 'Win'
            elif (home_score + spread) < away_score: return 'Loss'
            else: return 'Push'
            
        elif bet_on == away_team:
            spread = pred['market_line']
            if (away_score + spread) > home_score: return 'Win'
            elif (away_score + spread) < home_score: return 'Loss'
            else: return 'Push'

        return 'Pending'

if __name__ == "__main__":
    service = GradingService()
    res = service.grade_predictions()
    print(res)
