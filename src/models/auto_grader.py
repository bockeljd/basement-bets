
import sqlite3
from typing import List, Dict
from database import get_db_connection
from odds_client import OddsClient

class AutoGrader:
    def __init__(self):
        self.odds_client = OddsClient()
        
    def grade_pending_picks(self):
        """
        Main entry point.
        1. Fetch all 'Pending' predictions from DB.
        2. Fetch recent results from local DB (game_results joined with events).
        3. Match and Grade.
        4. Update DB.
        """
        pending = self._get_pending_picks()
        if not pending:
            return {"message": "No pending picks to grade."}
            
        # 2. Fetch Recent Local Results
        local_results = self._get_local_results()
        if not local_results:
            return {"message": "No local results found to grade against.", "pending_count": len(pending)}
            
        results_log = []
        for pick in pending:
            # We pass local_results as the score_data
            result = self._grade_pick(pick, local_results)
            if result:
                self._update_db(pick['id'], result)
                results_log.append(f"Pick {pick['id']} ({pick['matchup']}): {result}")
                    
        return {"graded_count": len(results_log), "logs": results_log}

    def _get_local_results(self):
        """
        Fetch game results from canonical database.
        """
        query = """
        SELECT 
            e.home_team, 
            e.away_team, 
            e.league, 
            e.start_time,
            r.home_score, 
            r.away_score, 
            r.final
        FROM game_results r
        JOIN events e ON r.event_id = e.id
        WHERE r.final = 1 OR r.final = 'true'
        ORDER BY e.start_time DESC
        LIMIT 1000
        """
        with get_db_connection() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]

    def _get_pending_picks(self):
        query = "SELECT * FROM model_predictions WHERE outcome IS NULL OR outcome = 'PENDING'"
        with get_db_connection() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]
            
    def _grade_pick(self, pick, scores_data):
        """
        Compare a single pick against a list of game scores.
        Returns 'Won', 'Lost', 'Push', or None (not found).
        """
        # Normalize matchup parsing
        # Pick matchup: "Away @ Home" usually (e.g. "Bills @ Chiefs")
        # But let's rely on team names.
        
        # Simple substring match against home/away teams in scores
        # scores_data is list of games from API.
        
        target_game = None
        for game in scores_data:
            if not game.get('completed'):
                continue
                
            # Check names. API has 'home_team' and 'away_team'.
            # Pick has 'matchup' string.
            # Split pick matchup
            if '@' in pick['matchup']:
                p_away, p_home = [x.strip() for x in pick['matchup'].split('@')]
            else:
                # unknown format
                continue
                
            # Heuristic: verify BOTH teams match
            # To handle partial names ("Bills" vs "Buffalo Bills"), check containment
            h_score_name = game['home_team']
            a_score_name = game['away_team']
            
            # Match logic: simple inclusion
            # "Bills" in "Buffalo Bills" -> True
            if (p_home in h_score_name or h_score_name in p_home) and \
               (p_away in a_score_name or a_score_name in p_away):
                target_game = game
                break
                
        if not target_game:
            return None
            
        # Found game, now grade it
        # Extract scores
        home_score = 0
        away_score = 0
        
        # API returns scores list in 'scores' or sometimes 'scores' is null?
        # The Odds API format: 'scores': [{'name': 'Team A', 'score': '20'}, ...]
        # Score is string, usually.
        
        raw_scores = target_game.get('scores')
        if not raw_scores:
            return None
            
        for s in raw_scores:
            if s['name'] == target_game['home_team']:
                home_score = float(s['score'])
            elif s['name'] == target_game['away_team']:
                away_score = float(s['score'])
                
        # Determine Winner/Spread
        bet_on = pick['bet_on']
        market = pick['market']
        line = pick['market_line'] # e.g. -2.5, 45.5, or Moneyline odds? 
        # Wait, for Moneyline, line is odds (-110). For Spread, line is the spread (-2.5).
        # We stored 'market_line' generically.
        # We need to know if it's Spread vs Moneyline vs Total.
        
        # Grading Logic
        try:
            if market == 'Spread':
                # Bet on Home Spd -2.5 -> Home Score + (-2.5) > Away Score
                # Bet on Away Spd +3 -> Away Score + (3) > Home Score
                
                # Identify which side was the bet
                # pick['bet_on'] is team name usually.
                
                team_score = 0
                opp_score = 0
                
                # Is bet_on Home or Away?
                if bet_on in target_game['home_team'] or target_game['home_team'] in bet_on:
                    team_score = home_score
                    opp_score = away_score
                else:
                    team_score = away_score
                    opp_score = home_score
                    
                # line is the spread relative to the bet_on team?
                # Usually: Bet on Bills -2.5. line = -2.5.
                # Result = (team_score + line) > opp_score
                
                if (team_score + line) > opp_score:
                    return 'Won'
                elif (team_score + line) < opp_score:
                    return 'Lost'
                else:
                    return 'Push'
                    
            elif market == 'Total':
                # Bet on OVER or UNDER
                total_score = home_score + away_score
                
                if bet_on.upper() == 'OVER':
                    return 'Won' if total_score > line else 'Lost' if total_score < line else 'Push'
                elif bet_on.upper() == 'UNDER':
                    return 'Won' if total_score < line else 'Lost' if total_score > line else 'Push'
                    
            elif market == 'Moneyline':
                # Straight up winner
                winner = target_game['home_team'] if home_score > away_score else target_game['away_team']
                # Check if bet_on matches winner
                if bet_on in winner or winner in bet_on:
                    return 'Won'
                else:
                    return 'Lost'
                    
        except Exception as e:
            print(f"Grading logic error for {pick['id']}: {e}")
            return None
            
        return None

    def _update_db(self, pick_id, outcome):
        query = "UPDATE model_predictions SET outcome = :o WHERE id = :id"
        with get_db_connection() as conn:
            conn.execute(query, {"o": outcome.upper(), "id": pick_id})
            conn.commit()
