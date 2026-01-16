import math
from typing import Dict, Tuple, Optional
from datetime import datetime
import sys
import os

# Adjust imports based on project structure
try:
    from src.database import get_db_connection, _exec
except ImportError:
    from database import get_db_connection, _exec

class NCAAMModelV1:
    """
    NCAAM V1: Efficiency/Tempo Model with Strict Snapshotting.
    """
    
    def __init__(self, sigma_margin: float = 11.0, sigma_total: float = 12.0):
        self.sigma_margin = sigma_margin
        self.sigma_total = sigma_total

    def _norm_cdf(self, x):
        """Standard Normal CDF."""
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def fetch_features(self, home_team: str, away_team: str, game_time: datetime) -> Optional[Dict]:
        """
        Fetch the latest metrics for both teams strictly BEFORE game_time.
        """
        query = """
        SELECT * FROM bt_team_metrics_daily 
        WHERE team_text = :team 
          AND date < :game_time 
        ORDER BY date DESC 
        LIMIT 1
        """
        
        with get_db_connection() as conn:
            # Home
            cur_h = _exec(conn, query, {"team": home_team, "game_time": game_time.isoformat()})
            home_row = cur_h.fetchone()
            
            # Away
            cur_a = _exec(conn, query, {"team": away_team, "game_time": game_time.isoformat()})
            away_row = cur_a.fetchone()
            
        if not home_row or not away_row:
            return None
            
        return {
            "home": dict(home_row),
            "away": dict(away_row)
        }

    def predict_score(self, features: Dict) -> Tuple[float, float]:
        """
        Predict scores using AdjOff and AdjTempo.
        Score = (AdjOff / 100) * Tempo.
        
        Logic V1 (Simple):
        Home Score = HomeAdjOff * GameTempo / 100
        Away Score = AwayAdjOff * GameTempo / 100
        
        Where GameTempo = (HomeAdjTempo + AwayAdjTempo) / 2  (Simplified)
        """
        h_stats = features['home']
        a_stats = features['away']
        
        # Simplified Tempo
        p_pace = (h_stats['adj_tempo'] + a_stats['adj_tempo']) / 2.0
        
        # Simplified Efficiency (Ignoring Opponent Def for V1 Basic)
        # Improvement: (HomeOff * AwayDef) / AvgEff
        home_score = (h_stats['adj_off'] / 100.0) * p_pace
        away_score = (a_stats['adj_off'] / 100.0) * p_pace
        
        return home_score, away_score

    def run_inference(self, home_team: str, away_team: str, game_time: datetime, market_spread: float = 0.0, market_total: float = 140.0) -> Dict:
        features = self.fetch_features(home_team, away_team, game_time)
        if not features:
            return {"error": "Missing valid snapshot data"}
            
        h_score, a_score = self.predict_score(features)
        
        proj_margin = h_score - a_score
        proj_total = h_score + a_score
        
        # Probabilities
        # Win (Margin > 0)
        z_win = (0 - proj_margin) / self.sigma_margin
        prob_win = 1.0 - self._norm_cdf(z_win)
        
        # Cover (Margin > MarketSpread)
        # Note: market_spread is typically "Home -3.5" -> 3.5 hurdle.
        z_cover = (market_spread - proj_margin) / self.sigma_margin
        prob_cover = 1.0 - self._norm_cdf(z_cover)
        
        # Over (Total > MarketTotal)
        z_over = (market_total - proj_total) / self.sigma_total
        prob_over = 1.0 - self._norm_cdf(z_over)
        
        return {
            "snapshot_date": features['home']['date'], # The snapshot used
            "implied_home_score": h_score,
            "implied_away_score": a_score,
            "implied_margin": proj_margin,
            "implied_total": proj_total,
            "win_prob": prob_win,
            "cover_prob": prob_cover,
            "over_prob": prob_over,
            "uncertainty": self.sigma_margin
        }
