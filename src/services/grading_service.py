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
        pending = [p for p in predictions if p.get('outcome') == 'PENDING' or p.get('outcome') is None]
        
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
            
            # Persist Scores for History (optional, but keep it if desired)
            for game in scores:
                self._persist_game_result(game)
            
            for p in preds:
                eval_res = self._evaluate_prediction(p, scores)
                # eval_res: {"outcome": "WON/LOST/PUSH/PENDING"}
                
                if eval_res and eval_res.get('outcome') != 'PENDING':
                    update_model_prediction_result(
                        p['id'], 
                        eval_res['outcome']
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
        game_id = pred.get('event_id') 
        
        match = None
        for s in scores:
            if s['id'] == game_id:
                match = s
                break
        
        # Fallback Matcher (if ID mismatch)
        if not match:
             pred_home = pred.get('home_team')
             pred_away = pred.get('away_team')
             
             raw_date = pred.get('analyzed_at') or ''
             pred_date = raw_date.split('T')[0] if raw_date else ''
             
             if pred_home:
                 for s in scores:
                      s_home = s.get('home_team', '')
                      if s_home == pred_home or (s_home and pred_home and (pred_home in s_home or s_home in pred_home)):
                           s_date_raw = s.get('commence_time', '').split('T')[0]
                           match_found = False
                           try:
                               p_dt = datetime.strptime(pred_date, '%Y-%m-%d')
                               s_dt = datetime.strptime(s_date_raw, '%Y-%m-%d')
                               if abs((p_dt - s_dt).days) <= 1:
                                   match_found = True
                           except:
                               if s_date_raw == pred_date:
                                   match_found = True
                                   
                           if match_found:
                               match = s
                               break
             
        if not match or not (match.get('completed') or match.get('status') in ['complete', 'final', 'completed']):
            return {"outcome": 'PENDING'}
            
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
        res = {"outcome": 'PENDING', "home_score": home_score, "away_score": away_score}

        # Evaluate Logic based on Market Type
        # New model outputs: pick, market_type, bet_line
        bet_on = pred.get('pick', '') 
        market = pred.get('market_type', '')
        line = pred.get('bet_line', 0)
        
        try:
            if market == 'SPREAD':
                team_score = home_score if bet_on == home_team else away_score
                opp_score = away_score if bet_on == home_team else home_score
                # line is relative to the picked team in v2
                if (team_score + line) > opp_score: res["outcome"] = 'WON'
                elif (team_score + line) < opp_score: res["outcome"] = 'LOST'
                else: res["outcome"] = 'PUSH'
                
            elif market == 'TOTAL':
                total_score = home_score + away_score
                if bet_on.upper() == 'OVER':
                    res["outcome"] = 'WON' if total_score > line else 'LOST' if total_score < line else 'PUSH'
                else:
                    res["outcome"] = 'WON' if total_score < line else 'LOST' if total_score > line else 'PUSH'
                    
            elif market == 'ML':
                winner = home_team if home_score > away_score else away_team
                res["outcome"] = 'WON' if bet_on == winner else 'LOST'
                
        except Exception as e:
            print(f"[GradingService] Eval error: {e}")
            return {"outcome": 'PENDING'}

        return res

    def _persist_game_result(self, game):
        """
        Parse game data and upsert to 'game_results' table.
        """
        from src.database import upsert_game_result
        try:
            home_score = None
            away_score = None
            
            if game.get('scores'):
                for s in game['scores']:
                    if s['name'] == game.get('home_team'):
                        home_score = s['score']
                    elif s['name'] == game.get('away_team'):
                        away_score = s['score']
            
            res_data = {
                'event_id': game.get('id'),
                'home_score': home_score,
                'away_score': away_score,
                'final': True if game.get('completed') else False,
                'period': game.get('status')
            }
            upsert_game_result(res_data)
        except Exception as e:
            print(f"[GradingService] Error persisting game {game.get('id')}: {e}")

if __name__ == "__main__":
    service = GradingService()
    res = service.grade_predictions()
    print(res)
