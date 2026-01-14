import random
from dataclasses import dataclass
import statistics

@dataclass
class SimResult:
    home_win_pct: float
    away_win_pct: float
    fair_spread: float
    fair_total: float
    home_score_avg: float
    away_score_avg: float
    edge_detected: bool = False
    volatility_edge: bool = False

class MonteCarloEngine:
    """
    Simulates sports matchups 10,000 times to account for variance (volatility).
    """

    def __init__(self, simulations: int = 10000):
        self.simulations = simulations

    def simulate_game(self, 
                      home_proj: float, home_vol: float, 
                      away_proj: float, away_vol: float,
                      vegas_spread: float = None, vegas_total: float = None) -> SimResult:
        """
        Runs the simulation loop.
        
        Args:
            home_proj: Projected score for Home Team (derived from Interaction Formula).
            home_vol: Standard Deviation of Home Team's recent scores.
            away_proj: Projected score for Away Team.
            away_vol: Standard Deviation of Away Team's scores.
            vegas_spread: Current market spread (Home - Away).
            vegas_total: Current market total.
        """
        
        home_scores = []
        away_scores = []
        home_wins = 0
        ties = 0

        for _ in range(self.simulations):
            # Monte Carlo Step: Sample from Normal Distribution
            h_score = random.gauss(home_proj, home_vol)
            a_score = random.gauss(away_proj, away_vol)
            
            # Sanity check: Non-negative scores (though purely theoretical gaussian can be negative)
            h_score = max(0, h_score)
            a_score = max(0, a_score)

            home_scores.append(h_score)
            away_scores.append(a_score)

            if h_score > a_score:
                home_wins += 1
            elif h_score == a_score:
                ties += 0.5 # Half win? Or ignore. Let's count half.
                home_wins += 0.5

        # Aggregation
        avg_home = statistics.mean(home_scores)
        avg_away = statistics.mean(away_scores)
        
        win_pct = (home_wins / self.simulations) * 100
        loss_pct = 100 - win_pct
        
        # Fair Spread: Home - Away (Positive means Home is favored by Model)
        # Wait, Spread convention: Favorite is -X. 
        # If Home is 24, Away is 20. Diff is +4. 
        # Fair Line would be Home -4.
        # So Fair Spread Value = -(Home - Away) usually.
        # Let's return the Margin: Home - Away.
        fair_margin = avg_home - avg_away
        fair_spread = -fair_margin # If Home wins by 4, Spread is -4.0
        
        fair_total = avg_home + avg_away
        
        # Edge Detection
        edge = False
        vol_edge = False
        
        if vegas_spread is not None:
            # Example: Vegas Home -3. Model Fair Home -7.
            # Edge on Home. 
            # Diff: |Vegas - Fair| > 3?
            if abs(vegas_spread - fair_spread) > 3.0:
                edge = True
                
        if vegas_total is not None:
            # Volatility Logic:
            # If Model Total > Vegas Total AND High Volatility -> Great Bet.
            if fair_total > vegas_total + 2.0: # Margin of safety
                # Check if high volatility (heuristic)
                # NFL high vol > 10? NCAAM > 12?
                # Just flag it if sim shows Over edge.
                vol_edge = True

        return SimResult(
            home_win_pct=round(win_pct, 1),
            away_win_pct=round(loss_pct, 1),
            fair_spread=round(fair_spread, 2),
            fair_total=round(fair_total, 2),
            home_score_avg=round(avg_home, 2),
            away_score_avg=round(avg_away, 2),
            edge_detected=edge,
            volatility_edge=vol_edge
        )

    def calculate_interaction(self, off_rating, def_rating, league_avg, tempo=1.0, is_epa=False):
        """
        Calculates projected score using the Interaction Formula.
        
        If EPA (NFL):
            Proj = (Off_EPA + Def_EPA - 0) * Plays + Base_Score?
            Actually User Formula: Proj EPA = Off + Def - Avg.
            Score = Proj EPA * Plays + League_Avg_Score (approx).
            
        If Efficiency (NCAAM):
            Proj_Eff = Off_Eff + Def_Eff - League_Avg_Eff
            Score = (Proj_Eff / 100) * Tempo
        """
        if is_epa:
            # Input ratings are EPA/Play.
            # Assuming league_avg EPA is roughly 0.0 (or modeled as such).
            # Net EPA = Off + Def (Def should be negative for good defense).
            
            # We need a Base Score (League Avg Points per Game).
            # NFL Avg ~ 21.5 pts.
            league_avg_score = 21.5
            
            # Adjusted EPA/Play
            net_epa = off_rating + def_rating - league_avg
            
            # Projected Score
            # EPA is points *added* roughly relative to average? 
            # Actually EPA sums to Total Points - Expected Points.
            # Let's estimate: Score = 21.5 + (Net_EPA * Tempo)
            return league_avg_score + (net_epa * tempo)
            
        else:
            # NCAAM Efficiency (Points per 100 Possessions)
            adj_eff = off_rating + def_rating - league_avg
            return (adj_eff / 100.0) * tempo

if __name__ == "__main__":
    eng = MonteCarloEngine(simulations=5000)
    
    # Test NFL Case: Chiefs vs Ravens
    # Chiefs Off EPA: +0.25
    # Ravens Def EPA: -0.15
    # Avg: 0.0
    # Tempo: 64 plays
    # Volatility: 10.0 (Guess)
    
    proj_home = eng.calculate_interaction(0.25, -0.15, 0.0, tempo=64, is_epa=True)
    # 21.5 + (0.10 * 64) = 21.5 + 6.4 = 27.9
    
    # Opponent (Ravens Off vs Chiefs Def)
    # Ravens Off: +0.20
    # Chiefs Def: -0.05
    proj_away = eng.calculate_interaction(0.20, -0.05, 0.0, tempo=64, is_epa=True)
    
    res = eng.simulate_game(proj_home, 10.0, proj_away, 10.0, vegas_spread=-3.5, vegas_total=50.0)
    print("NFL Test Result:", res)
