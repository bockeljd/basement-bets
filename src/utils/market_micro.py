
from typing import List, Dict, Optional, Tuple

class MarketMicrostructure:
    """
    Utilities for handling market data:
    - Devigging (removing vigorish to find Fair Price)
    - Line Shopping (finding best available price)
    """

    @staticmethod
    def devig_american_odds(odds_1: int, odds_2: int) -> Tuple[float, float]:
        """
        Calculate devigged probabilities from two sides of a market (e.g. -110/-110).
        Uses simple multiplicative or power method? 
        Standard method: Calculate implied probs, sum them, divide each by sum.
        """
        def implied(o):
            if o > 0: return 100 / (o + 100)
            else: return -o / (-o + 100)
            
        p1 = implied(odds_1)
        p2 = implied(odds_2)
        
        overround = p1 + p2
        return p1 / overround, p2 / overround

    @staticmethod
    def get_best_line(outcomes: List[Dict], side: str) -> Optional[Dict]:
        """
        Find the best line for a specific side (e.g. 'Home') from a list of market outcomes.
        outcomes: List of dicts, each from a different book.
        [{'book': 'DK', 'point': -5.5, 'price': -110}, ...]
        
        Logic:
        1. Sort by Point (descending for Under/Home, wait.. depends on handicap)
           For Spread (Home - Away):
             Buying Home (-5 is better than -6). So Max Point is better.
             Buying Away (+7 is better than +6). So Max Point (most positive) is better.
           Wait, -5 > -6. correct.
           
        2. Tiebreak by Price (Max Price, e.g. -105 > -110).
        """
        if not outcomes: return None
        
        # Helper to standardize sorting
        # We want MAX Point, then MAX Price.
        return max(outcomes, key=lambda x: (x.get('point', -9999), x.get('price', -9999)))

    @staticmethod
    def get_consensus_line(outcomes: List[Dict]) -> Optional[Dict]:
        """
        Calculate median line and price.
        """
        if not outcomes: return None
        sorted_outcomes = sorted(outcomes, key=lambda x: x.get('point', 0))
        n = len(sorted_outcomes)
        mid = n // 2
        return sorted_outcomes[mid]
