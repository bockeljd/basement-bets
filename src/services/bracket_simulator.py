
import json
import os
import random
import statistics
import math
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional

from src.database import get_db_connection, _exec
from src.utils.naming import standardize_team_name
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.services.kenpom_client import KenPomClient

class SimulatorDataError(Exception):
    """Raised when critical data for simulation is missing."""
    pass

class LiveBracketSimulator:
    """
    Simulates a full March Madness bracket using the calibrated 
    NCAAM Market-First Model and tournament-specific adjustments.
    """
    
    def __init__(self, simulations: int = 10000):
        self.simulations = simulations
        self.model = NCAAMMarketFirstModelV2()
        self.kp_client = KenPomClient()
        self._kp_cache = {}
        self.league_avg_eff = 106.0  # 2025-26 D1 average
        self.default_sigma = 10.5
        
    def _get_ratings(self, team_name: str) -> Dict[str, Any]:
        """Fetch KenPom ratings with caching."""
        key = standardize_team_name(team_name)
        if key not in self._kp_cache:
            ratings = self.kp_client.get_team_rating(key)
            if not ratings:
                # ZERO SILENT FALLBACKS
                raise SimulatorDataError(f"Missing KenPom ratings for '{team_name}' (standardized: '{key}')")
            self._kp_cache[key] = ratings
        return self._kp_cache[key]

    def simulate_game(self, team_a: str, team_b: str, round_index: int) -> Dict[str, Any]:
        """
        Simulate a single game using the model's fair-value logic 
        plus tournament adjustments like fatigue.
        """
        # Handle play-in variants (e.g. "Lehigh / Prairie View A&M" -> "Lehigh")
        # We take the first team as the representative for the simulation
        team_a = team_a.split(" / ")[0].split(" - ")[0].strip()
        team_b = team_b.split(" / ")[0].split(" - ")[0].strip()

        # Round 1 (R64) is Index 0. 
        # Round 2 (R32) is Index 1, etc.
        
        # 1. Get Base Ratings (Validation happens here)
        a_ratings = self._get_ratings(team_a)
        b_ratings = self._get_ratings(team_b)
        
        # 2. Calculate Base Projections (Interaction Formula)
        h_eff = a_ratings['adj_o'] + b_ratings['adj_d'] - self.league_avg_eff
        a_eff = b_ratings['adj_o'] + a_ratings['adj_d'] - self.league_avg_eff
        avg_tempo = (a_ratings['adj_t'] + b_ratings['adj_t']) / 2.0
        
        # Points = (Eff/100) * Tempo
        h_proj = (h_eff / 100.0) * avg_tempo
        a_proj = (a_eff / 100.0) * avg_tempo
        
        # 3. Apply Bounded Tournament Adjustments
        # Fatigue: If it's the second game of the weekend (R32, Elite 8), apply fatigue.
        fatigue_adj_a = 0.0
        fatigue_adj_b = 0.0
        
        if round_index in [1, 3, 5]:  # R32, E8, Championship
            # Short rest penalty (-1.5 to -2.5 based on tournament intensity)
            fatigue_adj_a = -1.5
            fatigue_adj_b = -1.5
            
        # 4. Monte Carlo Simulation
        sigma = self.default_sigma
        # Tempo scaling for sigma (Higher tempo => Higher variance)
        tempo_factor = math.sqrt(avg_tempo / 68.0)
        actual_sigma = sigma * tempo_factor
        
        h_wins = 0
        h_scores = []
        a_scores = []
        
        # Per-team variance is sigma / sqrt(2)
        team_vol = actual_sigma / 1.4142
        
        for _ in range(self.simulations):
            # Apply fatigue to the projected mean
            h = max(0, random.gauss(h_proj + fatigue_adj_a, team_vol))
            a = max(0, random.gauss(a_proj + fatigue_adj_b, team_vol))
            h_scores.append(h)
            a_scores.append(a)
            if h > a:
                h_wins += 1
            elif h == a:
                h_wins += 0.5
                
        win_prob_a = (h_wins / self.simulations) * 100
        win_prob_b = 100 - win_prob_a
        fair_spread = -(statistics.mean(h_scores) - statistics.mean(a_scores))
        fair_total = statistics.mean(h_scores) + statistics.mean(a_scores)
        
        winner = team_a if win_prob_a >= win_prob_b else team_b
        
        return {
            "team_a": team_a,
            "team_b": team_b,
            "spread": round(fair_spread, 2),
            "total": round(fair_total, 2),
            "win_prob_a": round(win_prob_a, 1),
            "win_prob_b": round(win_prob_b, 1),
            "winner": winner,
            "round_index": round_index,
            "summary": f"LiveSim | σ:{round(actual_sigma, 2)} | Rest Adj:{fatigue_adj_a:+.1f}"
        }

    def simulate_full_bracket(self, seeds: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Simulate all games from R64 to Championship.
        Seeds structure: { "East": [ {"team_name": "...", "seed": 1}, ... ], ... }
        """
        output = {
            "season": "2025-26",
            "rounds": {},
            "final_four": [],
            "championship": None,
            "champion": None,
            "simulated_at": datetime.now().isoformat()
        }
        
        regional_winners = {}
        
        for region in ["East", "South", "West", "Midwest"]:
            region_seeds = seeds.get(region, [])
            if not region_seeds:
                continue

            # Standard bracket pairing: (1,16), (8,9), (5,12), (4,13), (6,11), (3,14), (7,10), (2,15)
            # The seeds list is usually ordered by seed.
            ordered_teams = sorted(region_seeds, key=lambda x: x['seed'])
            team_map = {t['seed']: t['team_name'] for t in ordered_teams}
            
            r64_pairings = [
                (1, 16), (8, 9), (5, 12), (4, 13),
                (6, 11), (3, 14), (7, 10), (2, 15)
            ]
            
            r64_matchups = [(team_map[p[0]], team_map[p[1]]) for p in r64_pairings if p[0] in team_map and p[1] in team_map]
            
            # Simulate R64
            r64_results = []
            for ta, tb in r64_matchups:
                r64_results.append(self.simulate_game(ta, tb, 0))
            
            # Simulate R32
            r32_matchups = []
            for i in range(0, len(r64_results), 2):
                r32_matchups.append((r64_results[i]['winner'], r64_results[i+1]['winner']))
            
            r32_results = []
            for ta, tb in r32_matchups:
                r32_results.append(self.simulate_game(ta, tb, 1))
                
            # Simulate Sweet 16
            s16_matchups = []
            for i in range(0, len(r32_results), 2):
                s16_matchups.append((r32_results[i]['winner'], r32_results[i+1]['winner']))
                
            s16_results = []
            for ta, tb in s16_matchups:
                s16_results.append(self.simulate_game(ta, tb, 2))
                
            # Simulate Elite 8
            if len(s16_results) >= 2:
                e8_matchups = [(s16_results[0]['winner'], s16_results[1]['winner'])]
                e8_results = [self.simulate_game(e8_matchups[0][0], e8_matchups[0][1], 3)]
                regional_winners[region] = e8_results[0]['winner']
            else:
                e8_results = []
            
            output["rounds"][region] = {
                "round_of_64": r64_results,
                "round_of_32": r32_results,
                "sweet_16": s16_results,
                "elite_8": e8_results
            }

        # Final Four
        # Pairings: East vs West, South vs Midwest (Traditional)
        e_win = regional_winners.get("East")
        w_win = regional_winners.get("West")
        s_win = regional_winners.get("South")
        m_win = regional_winners.get("Midwest")

        if e_win and w_win:
            ff_results = [self.simulate_game(e_win, w_win, 4)]
        else:
            ff_results = []
            
        if s_win and m_win:
            ff_results.append(self.simulate_game(s_win, m_win, 4))
            
        output["final_four"] = ff_results
        
        # Championship
        if len(ff_results) == 2:
            champ_matchup = (ff_results[0]['winner'], ff_results[1]['winner'])
            champ_result = self.simulate_game(champ_matchup[0], champ_matchup[1], 5)
            output["championship"] = champ_result
            output["champion"] = champ_result['winner']
        
        return output

    def get_seeds_from_db(self) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch seeds from ncaam_tournament_seeds table."""
        with get_db_connection() as conn:
            rows = _exec(conn, """
                SELECT team_name, seed, region
                FROM ncaam_tournament_seeds
                WHERE season = '2025-26'
                ORDER BY region, seed
            """).fetchall()
            
        seeds_by_region = {}
        for r in rows:
            reg = r['region']
            if reg not in seeds_by_region:
                seeds_by_region[reg] = []
            seeds_by_region[reg].append(dict(r))
        return seeds_by_region
