import math
from typing import Dict, Any, List

class RiskManager:
    """
    Handles all risk-related calculations including de-vigging,
    EV, and Kelly sizing.
    """

    def de_vig(self, odds: List[int]) -> List[float]:
        """
        Calculates fair probabilities from American odds by removing the "vig".
        Input: List of American odds [ -110, +110 ]
        Output: List of probabilities [ 0.5, 0.5 ]
        """
        implied_probs = []
        for o in odds:
            if o > 0:
                implied_probs.append(100 / (o + 100))
            else:
                implied_probs.append(abs(o) / (abs(o) + 100))
        
        total_p = sum(implied_probs)
        return [p / total_p for p in implied_probs]

    def calculate_ev(self, win_prob: float, american_odds: int) -> float:
        """
        Calculates Expected Value (EV) percentage.
        EV = (WinProb * Profit) - (LossProb * Stake)
        """
        if american_odds > 0:
            decimal_odds = (american_odds / 100) + 1
        else:
            decimal_odds = (100 / abs(american_odds)) + 1
            
        profit = decimal_odds - 1
        ev = (win_prob * profit) - (1 - win_prob)
        return ev * 100 # Return as percentage

    def kelly_size(self, win_prob: float, american_odds: int, bankroll: float, fraction: float = 0.25) -> Dict[str, Any]:
        """
        Calculates suggested bet size using Kelly Criterion.
        f* = (p * b - q) / b
        where p = win prob, q = loss prob, b = decimal odds - 1
        'fraction' is used for Fractional Kelly (0.25 = Quarter Kelly) to reduce variance.
        """
        if american_odds > 0:
            b = (american_odds / 100)
        else:
            b = (100 / abs(american_odds))
            
        q = 1 - win_prob
        
        kelly_f = (win_prob * b - q) / b if b > 0 else 0
        
        # Apply fractional Kelly and cap at 5% of bankroll for safety
        suggested_f = max(0, kelly_f * fraction)
        suggested_f = min(suggested_f, 0.05) 
        
        suggested_stake = suggested_f * bankroll
        
        return {
            "full_kelly": kelly_f,
            "suggested_fraction": suggested_f,
            "suggested_stake": round(suggested_stake, 2),
            "bankroll_pct": round(suggested_f * 100, 2)
        }

    def explain_decision(self, win_prob: float, market_odds: int, bankroll: float) -> str:
        """
        Provides a human-readable explanation of the risk assessment.
        """
        ev = self.calculate_ev(win_prob, market_odds)
        sizing = self.kelly_size(win_prob, market_odds, bankroll)
        
        if ev <= 0:
            return f"No edge found. EV is {ev:.1f}%. Avoid this bet."
        
        return f"Positive edge detected ({ev:.1f}% EV). Suggested stake is ${sizing['suggested_stake']} ({sizing['bankroll_pct']}% of bankroll) based on Quarter Kelly."
