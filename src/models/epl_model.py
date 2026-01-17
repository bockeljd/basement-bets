import math
from typing import Dict, Any, List
from src.models.base_model import BaseModel

# Pure Python Poisson PMF
def poisson_pmf(k: int, lam: float) -> float:
    return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)

class EPLModel(BaseModel):
    def __init__(self):
        super().__init__(sport_key="soccer_epl")
        self.team_ratings = {} # Map of team -> {attack, defense}

    def fetch_data(self):
        """
        Static xG ratings for top EPL teams.
        Attack = Expected goals scored per game vs avg defense.
        Defense = Expected goals conceded per game vs avg attack.
        """
        self.team_ratings = {
            "Manchester City": {"att": 2.4, "def": 0.8},
            "Liverpool": {"att": 2.2, "def": 0.9},
            "Arsenal": {"att": 2.1, "def": 0.7},
            "Aston Villa": {"att": 1.9, "def": 1.2},
            "Tottenham Hotspur": {"att": 1.8, "def": 1.3},
            "Newcastle United": {"att": 1.7, "def": 1.4},
            "Manchester United": {"att": 1.5, "def": 1.4},
            "Chelsea": {"att": 1.6, "def": 1.5},
            "West Ham United": {"att": 1.4, "def": 1.6},
            "Brighton": {"att": 1.6, "def": 1.7}
        }
        self.league_avg_goals = 1.6 # Per team per game

    def predict(self, game_id: str, home_team: str, away_team: str, market_odds: Dict[str, float] = None) -> Dict[str, Any]:
        """
        Poisson Model for Soccer Moneyline:
        Home Lambda = Home Att * Away Def / League Avg
        Away Lambda = Away Att * Home Def / League Avg
        """
        if not self.team_ratings:
            self.fetch_data()

        h = self.team_ratings.get(home_team, {"att": 1.5, "def": 1.5})
        a = self.team_ratings.get(away_team, {"att": 1.5, "def": 1.5})
        
        home_lambda = (h['att'] * a['def']) / self.league_avg_goals
        away_lambda = (a['att'] * h['def']) / self.league_avg_goals
        
        # Calculate probabilities for scores up to 5-5
        # Pure Python Matrix Logic
        prob_home_win = 0.0
        prob_draw = 0.0
        prob_away_win = 0.0
        
        max_goals = 6
        total_p = 0.0
        
        for i in range(max_goals): # Home goals
            p_home_i = poisson_pmf(i, home_lambda)
            for j in range(max_goals): # Away goals
                p_away_j = poisson_pmf(j, away_lambda)
                
                joint_prob = p_home_i * p_away_j
                total_p += joint_prob
                
                if i > j:
                    prob_home_win += joint_prob
                elif i == j:
                    prob_draw += joint_prob
                else:
                    prob_away_win += joint_prob
        
        # Normalize (since we truncated infinite series at 5 goals)
        if total_p > 0:
            prob_home_win /= total_p
            prob_draw /= total_p
            prob_away_win /= total_p
        
        fair_odds_home = 1 / prob_home_win if prob_home_win > 0 else 999
        
        return {
            "game_id": game_id,
            "win_prob_home": prob_home_win,
            "win_prob_draw": prob_draw,
            "win_prob_away": prob_away_win,
            "fair_odds_home": fair_odds_home,
            "model_version": "2024-01-14-epl-v1-py"
        }



    def find_edges(self):
        return []

    def evaluate(self, predictions: List[Dict[str, Any]]):
        pass
