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

    @abstractmethod
    def evaluate(self, predictions: List[Dict[str, Any]]):
        """
        Optional: Evaluate performance of a batch of predictions.
        """
        pass
