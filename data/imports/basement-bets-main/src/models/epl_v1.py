import math
from typing import Dict, Tuple, List
from datetime import datetime
import sys
import os

# Adjust imports based on project structure
try:
    from src.database import get_db_connection, _exec
except ImportError:
    from database import get_db_connection, _exec

class EPLModelV1:
    """
    EPL V1: Rolling Poisson Distribution Model.
    """
    
    def __init__(self, window_size: int = 20, shrinkage: float = 0.1):
        self.window_size = window_size
        self.shrinkage = shrinkage # Pull towards league average

    def _poisson_prob(self, lamb: float, k: int) -> float:
        return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

    def fetch_history(self, league: str, before_date: datetime) -> List[Dict]:
        """
        Fetch last N completed games for calculating team strength.
        """
        # Note: In a real system we'd optimize this to not fetch raw rows every inference.
        # But for V1 it's robust.
        query = """
        SELECT e.home_team, e.away_team, r.home_score, r.away_score 
        FROM events e
        JOIN game_results r ON e.id = r.event_id
        WHERE e.league = :league 
          AND e.start_time < :date
          AND r.final_flag = TRUE
        ORDER BY e.start_time DESC
        LIMIT 200 -- Fetch enough for context
        """
        with get_db_connection() as conn:
            cursor = _exec(conn, query, {"league": league, "date": before_date.isoformat()})
            return [dict(row) for row in cursor.fetchall()]

    def calculate_strengths(self, history: List[Dict], target_home: str, target_away: str) -> Tuple[float, float, float, float]:
        """
        Calculate Attack/Defense strengths for Home and Away team.
        Returns: (HomeAttack, HomeDef, AwayAttack, AwayDef)
        """
        # 1. Calc League Averages (Goals per game)
        total_goals = 0
        games_count = len(history)
        if games_count == 0:
            return 1.0, 1.0, 1.0, 1.0, 1.35 # Default
            
        for g in history:
            total_goals += (g['home_score'] + g['away_score'])
        
        avg_goals_per_team = (total_goals / 2.0) / games_count
        if avg_goals_per_team == 0: avg_goals_per_team = 1.35 # Fallback
        
        # 2. Filter for specific teams (last N games)
        # Simplified: Just take average goals scored/conceded vs league avg
        # A more complex solver (Dixon-Coles) minimizes error, 
        # but here we do Ratio method: (GoalsScored / Games) / LeagueAvg
        
        def get_team_stats(team, is_home_context):
            scored = 0
            conceded = 0
            count = 0
            for g in history:
                if count >= self.window_size: break
                if g['home_team'] == team:
                    scored += g['home_score']
                    conceded += g['away_score']
                    count += 1
                elif g['away_team'] == team:
                    scored += g['away_score']
                    conceded += g['home_score']
                    count += 1
            
            if count < 5: return 1.0, 1.0 # Not enough samples, regress to mean
            
            att = (scored / count) / avg_goals_per_team
            defn = (conceded / count) / avg_goals_per_team
            return att, defn

        h_att, h_def = get_team_stats(target_home, True)
        a_att, a_def = get_team_stats(target_away, False)
        
        # Apply Shrinkage
        # strength = (strength * (1-shrinkage)) + (1.0 * shrinkage)
        h_att = h_att * (1 - self.shrinkage) + self.shrinkage
        h_def = h_def * (1 - self.shrinkage) + self.shrinkage
        a_att = a_att * (1 - self.shrinkage) + self.shrinkage
        a_def = a_def * (1 - self.shrinkage) + self.shrinkage
        
        return h_att, h_def, a_att, a_def, avg_goals_per_team

    def run_inference(self, home_team: str, away_team: str, game_time: datetime, league: str = 'PL') -> Dict:
        history = self.fetch_history(league, game_time)
        h_att, h_def, a_att, a_def, league_avg = self.calculate_strengths(history, home_team, away_team)
        
        # Lambda calc
        # Home Goals = H_Att * A_Def * LeagueAvg * HomeAdv
        home_adv = 1.2 # Static 1.2x boost for home goals? Or +0.3 goals? 
        # Let's use multiplier 1.25 roughly standard for EPL
        
        lambda_home = h_att * a_def * league_avg * 1.20
        lambda_away = a_att * h_def * league_avg
        
        # Calculate Probabilities
        max_goals = 10
        prob_matrix = [[0.0] * max_goals for _ in range(max_goals)]
        
        p_home_win = 0.0
        p_draw = 0.0
        p_away_win = 0.0
        p_over_2_5 = 0.0
        
        for h in range(max_goals):
            for a in range(max_goals):
                p = self._poisson_prob(lambda_home, h) * self._poisson_prob(lambda_away, a)
                prob_matrix[h][a] = p
                
                if h > a: p_home_win += p
                elif h == a: p_draw += p
                else: p_away_win += p
                
                if (h + a) > 2.5: p_over_2_5 += p
        
        return {
            "predicted_home_goals": lambda_home,
            "predicted_away_goals": lambda_away,
            "win_prob": p_home_win,
            "draw_prob": p_draw,
            "away_prob": p_away_win,
            "over_2_5_prob": p_over_2_5,
            "uncertainty": 0.0 # TODO: Poisson variance?
        }
