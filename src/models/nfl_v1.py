import math
from typing import Dict, Tuple

class NFLModelV1:
    """
    NFL V1: Probabilistic Model using Normal Distributions for Margin and Total.
    """
    
    def __init__(self, sigma_margin: float = 13.5, sigma_total: float = 11.0):
        self.sigma_margin = sigma_margin
        self.sigma_total = sigma_total
        self.calibration_a = 0.0 # Placeholder for Platt Scaling 'A'
        self.calibration_b = 0.0 # Placeholder for Platt Scaling 'B'

    def _norm_cdf(self, x):
        """Standard Normal CDF."""
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def predict_margin_probs(self, projected_margin: float, market_spread: float) -> Tuple[float, float, float]:
        """
        Calculate Win and Cover probabilities.
        projected_margin: Score_Home - Score_Away (e.g. +3.5 means Home wins by 3.5)
        market_spread: The line to beat. NOTE: Market spread is usually presented as 'Home +3.5' (-3.5 numeric).
                       If line is Home -3.5, logic is Home Score - Away Score > 3.5.
                       So we compare Margin > -1 * SpreadValue? 
                       Standard convention: Spread is Home Team's line. -3.5 means Home must win by >3.5.
                       So we check P(Margin > -Spread).
                       Wait, logic check:
                       Home -3.5. Home must win by 4. Margin > 3.5.
                       Let's stick to: market_line is the number the margin must EXCEED.
        """
        # Win Prob (Margin > 0)
        z_win = (0 - projected_margin) / self.sigma_margin
        prob_loss = self._norm_cdf(z_win) # P(M < 0)
        prob_win = 1.0 - prob_loss
        
        # Cover Prob (Margin > Line)
        # If market_spread is -3.5 (Home favored), margin must be > 3.5.
        # So we want P(M > -market_spread) if input is traditionally formatted?
        # Let's standardize input: market_line_to_cover.
        # e.g. for Home -3.5, line_to_cover = 3.5.
        # e.g. for Home +3.5, line_to_cover = -3.5.
        
        # Let's assume input `market_spread` is the hurdle. 
        # i.e. "Home -3.5" -> market_spread = 3.5.
        
        z_cover = (market_spread - projected_margin) / self.sigma_margin
        prob_cover = 1.0 - self._norm_cdf(z_cover)
        
        return prob_win, prob_cover, 0.5 # flat push prob or ignoring for now

    def predict_total_probs(self, projected_total: float, market_total: float) -> Tuple[float, float]:
        """
        Calculate Over/Under probabilities.
        """
        z_over = (market_total - projected_total) / self.sigma_total
        prob_over = 1.0 - self._norm_cdf(z_over)
        prob_under = self._norm_cdf(z_over)
        
        return prob_over, prob_under

    def calibrate(self, raw_prob: float) -> float:
        """
        Apply Platt Scaling (Sigmoid).
        P_calib = 1 / (1 + exp(A * f(x) + B)) 
        Here we assume raw_prob IS f(x) or we map logit first.
        Simple implementation: No-op if A=0, B=0 (defaults).
        """
        # TODO: Implement actual logistic regression application
        return raw_prob

    def run_inference(self, game_data: Dict) -> Dict:
        """
        Main entry point for a single game.
        """
        home_proj = game_data.get('projected_home_score')
        away_proj = game_data.get('projected_away_score')
        
        if home_proj is None or away_proj is None:
            return {}
            
        proj_margin = home_proj - away_proj
        proj_total = home_proj + away_proj
        
        market_spread = game_data.get('market_spread_hurdle', 0.0) # e.g. 3.5 for -3.5
        market_total = game_data.get('market_total_hurdle', 45.0)
        
        p_win, p_cover, _ = self.predict_margin_probs(proj_margin, market_spread)
        p_over, p_under = self.predict_total_probs(proj_total, market_total)
        
        return {
            "win_prob": self.calibrate(p_win),
            "cover_prob": self.calibrate(p_cover),
            "over_prob": self.calibrate(p_over),
            "implied_margin": proj_margin,
            "implied_total": proj_total,
            "uncertainty": self.sigma_margin
        }
