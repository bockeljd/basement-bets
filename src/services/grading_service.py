import os
import requests
import json
import sqlite3
from datetime import datetime, timedelta
import sys

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import fetch_model_history, update_model_prediction_result, upsert_game
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
                
            # Fetch scores
            scores = self._fetch_scores(sport_key, days=7)
            if not scores:
                print(f"  [WARN] No scores fetched for {sport} ({sport_key})")
                continue
            
            # Persist Scores for History
            for game in scores:
                self._persist_game_result(game)
            
            for p in preds:
                eval_res = self._evaluate_prediction(p, scores)
                # eval_res: {"result": "Win/Loss/Pending", "home_score": X, "away_score": Y}
                
                if eval_res and eval_res.get('result') != 'Pending':
                    update_model_prediction_result(
                        p['id'], 
                        eval_res['result'],
                        home_score=eval_res.get('home_score'),
                        away_score=eval_res.get('away_score')
                    )
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
        
        match = None
        for s in scores:
            if s['id'] == game_id:
                match = s
                break
        
        # Fallback Matcher (if ID mismatch)
        if not match:
             # Try to get teams from columns OR parse from matchup string
             pred_home = pred.get('home_team')
             pred_away = pred.get('away_team')
             
             if not pred_home and pred.get('matchup'):
                 # Matchup strings: "Team A @ Team B" or "Team A vs Team B"
                 if ' @ ' in pred['matchup']:
                     parts = pred['matchup'].split(' @ ')
                     pred_away, pred_home = parts[0], parts[1]
                 elif ' vs ' in pred['matchup']:
                     parts = pred['matchup'].split(' vs ')
                     pred_away, pred_home = parts[0], parts[1]

             raw_date = pred.get('date') or ''
             pred_date = raw_date.split('T')[0] if raw_date else ''
             
             if pred_home:
                 for s in scores:
                      # Check team name (fuzzy or normalized)
                      s_home = s.get('home_team', '')
                      if s_home == pred_home or (s_home and pred_home and (pred_home in s_home or s_home in pred_home)):
                           s_date_raw = s.get('commence_time', '').split('T')[0]
                           
                           # Fuzzy date match (+/- 1 day for UTC)
                           match_found = False
                           try:
                               from datetime import datetime, timedelta
                               p_dt = datetime.strptime(pred_date, '%Y-%m-%d')
                               s_dt = datetime.strptime(s_date_raw, '%Y-%m-%d')
                               if abs((p_dt - s_dt).days) <= 1:
                                   match_found = True
                           except:
                               if s_date_raw == pred_date:
                                   match_found = True
                                   
                           if match_found:
                               match = s
                               print(f"  [GRADING] Matched by Name: {pred_home} (Date: {s_date_raw} vs {pred_date})")
                               break
             
        if not match or not (match.get('completed') or match.get('status') in ['complete', 'final', 'completed']):
            return {"result": 'Pending', "home_score": None, "away_score": None}
            
        final_scores = match.get('scores')
        if not final_scores: return {"result": 'Pending', "home_score": None, "away_score": None}
        
        home_team = match['home_team']
        away_team = match['away_team']
        
        home_score = 0
        away_score = 0
        
        for fs in final_scores:
            if fs['name'] == home_team:
                home_score = int(fs['score'])
            elif fs['name'] == away_team:
                away_score = int(fs['score'])
                
        # Prepare Response
        res = {
            "result": 'Pending',
            "home_score": home_score,
            "away_score": away_score
        }

        # Evaluate Logic based on Market Type
        bet_on = pred['bet_on'] 
        
        # 1. Moneyline
        if "HOME" in bet_on and "(" in bet_on:
            if home_score > away_score: res["result"] = 'Win'
            elif home_score == away_score: res["result"] = 'Loss'
            else: res["result"] = 'Loss'
        elif "AWAY" in bet_on and "(" in bet_on:
             if away_score > home_score: res["result"] = 'Win'
             else: res["result"] = 'Loss'
        elif "DRAW" in bet_on:
             if home_score == away_score: res["result"] = 'Win'
             else: res["result"] = 'Loss'
             
        # 2. Spreads / Totals (NFL/NCAAM)
        elif "OVER" in bet_on:
            total_score = home_score + away_score
            line = pred['market_line']
            if total_score > line: res["result"] = 'Win'
            elif total_score < line: res["result"] = 'Loss'
            else: res["result"] = 'Push'
            
        elif "UNDER" in bet_on:
            total_score = home_score + away_score
            line = pred['market_line']
            if total_score < line: res["result"] = 'Win'
            elif total_score > line: res["result"] = 'Loss'
            else: res["result"] = 'Push'
            
        elif bet_on == home_team:
            spread = pred['market_line']
            if (home_score + spread) > away_score: res["result"] = 'Win'
            elif (home_score + spread) < away_score: res["result"] = 'Loss'
            else: res["result"] = 'Push'
            
        elif bet_on == away_team:
            spread = pred['market_line']
            if (away_score + spread) > home_score: res["result"] = 'Win'
            elif (away_score + spread) < home_score: res["result"] = 'Loss'
            else: res["result"] = 'Push'

        return res

    def _persist_game_result(self, game):
        """
        Parse game data and upsert to 'games' table.
        """
        try:
            home_score = None
            away_score = None
            
            if game.get('scores'):
                for s in game['scores']:
                    if s['name'] == game.get('home_team'):
                        home_score = s['score']
                    elif s['name'] == game.get('away_team'):
                        away_score = s['score']
            
            game_data = {
                'game_id': game.get('id'),
                'sport_key': game.get('sport_key'),
                'commence_time': game.get('commence_time'),
                'home_team': game.get('home_team'),
                'away_team': game.get('away_team'),
                'home_score': home_score,
                'away_score': away_score,
                'status': 'completed' if game.get('completed') else 'scheduled'
            }
            
            upsert_game(game_data)
        except Exception as e:
            print(f"[GradingService] Error persisting game {game.get('id')}: {e}")

if __name__ == "__main__":
    service = GradingService()
    res = service.grade_predictions()
    print(res)
