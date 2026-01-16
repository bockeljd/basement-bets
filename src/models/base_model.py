from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseModel(ABC):
    """
    Abstract Base Class for all sport-specific models.
    Enforces the 'Toyota Hilux' standard of reliability.
    """

    def __init__(self, sport_key: str):
        self.sport_key = sport_key

    @abstractmethod
    def fetch_data(self):
        """
        Fetch necessary data (stats, injuries, etc.) to run the model.
        Should handle caching internally.
        """
        pass

    @abstractmethod
    def predict(self, game_id: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Generate a prediction for a specific game.
        Returns a dictionary with:
        - fair_spread
        - fair_total
        - win_prob_home
        - edge (calculated against market)
        """
        pass

    def apply_feature_adjustments(self, base_prob: float, features: List[Dict[str, Any]]) -> float:
        """
        Adjusts a baseline probability based on qualitative FeatureEvents.
        Features have: direction (positive/negative), magnitude_hint (low/medium/high).
        """
        adj = 0.0
        magnitude_map = {
            "low": 0.02,
            "medium": 0.05,
            "high": 0.10
        }
        
        for f in features:
            mag = magnitude_map.get(f.get('magnitude_hint', 'low'), 0.02)
            direction = 1 if f.get('direction') == 'positive' else -1 if f.get('direction') == 'negative' else 0
            adj += (direction * mag)
            
        final_prob = max(0.01, min(0.99, base_prob + adj))
        return final_prob

    @abstractmethod
    def evaluate(self, predictions: List[Dict[str, Any]]):
        """
        Optional: Evaluate performance of a batch of predictions.
        """
        pass
