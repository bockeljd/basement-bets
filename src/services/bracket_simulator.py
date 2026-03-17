
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
    Thin wrapper delegating to the canonical NCAAMTournamentPredictionService.
    Preserved to avoid breaking legacy imports while transitioning.
    """
    
    def __init__(self, simulations: int = 10000):
        from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService
        self.simulations = simulations
        self.service = NCAAMTournamentPredictionService()

    def simulate_game(self, team_a: str, team_b: str, round_index: int) -> Dict[str, Any]:
        """
        Delegates single game simulation.
        """
        from src.services.ncaam_tournament_service import TournamentGameInput
        
        # We trust the upstream caller to pass clean team names. 
        # First Four games will be simulated directly and advance their winners as independent nodes.
        team_a_clean = team_a.strip()
        team_b_clean = team_b.strip()
        
        res = self.service.predict_game(TournamentGameInput(
            team_a=team_a_clean, team_b=team_b_clean, round_index=round_index, neutral_site=True
        ))
        
        # Format as legacy for older scripts if they directly call this (though we update scripts in Phase 5)
        return {
            "team_a": res.team_a,
            "team_b": res.team_b,
            "spread": res.projected_spread_a,
            "total": res.projected_total,
            "win_prob_a": res.win_prob_a,
            "win_prob_b": res.win_prob_b,
            "winner": res.winner,
            "round_index": round_index,
            "summary": "Canonical | " + ", ".join(res.reason_codes + res.risk_flags)
        }

    def simulate_full_bracket(self, seeds: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Delegates full Monte Carlo bracket simulation to the canonical service.
        Returns a dictified version of TournamentBracketSimulation.
        """
        res = self.service.simulate_bracket(seeds, simulations=self.simulations)
        return res.model_dump()

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
                
            team_name = r['team_name']
            # Production Hotfix: DB has legacy slash-combined play-ins (e.g. "Howard / Wagner")
            # We split them into discrete entries so the canonical simulator treats them as the First Four
            if " / " in team_name:
                teams = team_name.split(" / ")
                seeds_by_region[reg].append({"team_name": teams[0].strip(), "seed": r['seed'], "region": reg})
                seeds_by_region[reg].append({"team_name": teams[1].strip(), "seed": r['seed'], "region": reg})
            else:
                seeds_by_region[reg].append(dict(r))
                
        return seeds_by_region
