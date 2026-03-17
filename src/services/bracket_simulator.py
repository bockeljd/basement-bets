
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
            
        if not rows:
            print("[Simulator] WARNING: No seeds found in DB for 2025-26. Using hardcoded fallback.")
            return HARDCODED_2026_SEEDS

        seeds_by_region = {}
        split_count = 0
        for r in rows:
            reg = r['region']
            if reg not in seeds_by_region:
                seeds_by_region[reg] = []
            
            tname = r['team_name']
            if " / " in tname:
                teams = [t.strip() for t in tname.split(" / ")]
                for t in teams:
                    new_row = dict(r)
                    new_row['team_name'] = t
                    seeds_by_region[reg].append(new_row)
                split_count += 1
            else:
                seeds_by_region[reg].append(dict(r))
        
        if split_count > 0:
            print(f"[Simulator] Split {split_count} slash-combined play-in rows.")
            
        return seeds_by_region

HARDCODED_2026_SEEDS = {
    "East": [
        {"seed": 1, "team_name": "Duke Blue Devils"}, {"seed": 16, "team_name": "Siena Saints"},
        {"seed": 8, "team_name": "Ohio State Buckeyes"}, {"seed": 9, "team_name": "TCU Horned Frogs"},
        {"seed": 5, "team_name": "St. John's Red Storm"}, {"seed": 12, "team_name": "Northern Iowa Panthers"},
        {"seed": 4, "team_name": "Kansas Jayhawks"}, {"seed": 13, "team_name": "Cal Baptist Lancers"},
        {"seed": 6, "team_name": "Louisville Cardinals"}, {"seed": 11, "team_name": "South Florida Bulls"},
        {"seed": 3, "team_name": "Michigan State Spartans"}, {"seed": 14, "team_name": "North Dakota State Bison"},
        {"seed": 7, "team_name": "UCLA Bruins"}, {"seed": 10, "team_name": "UCF Knights"},
        {"seed": 2, "team_name": "UConn Huskies"}, {"seed": 15, "team_name": "Furman Paladins"}
    ],
    "South": [
        {"seed": 1, "team_name": "Florida Gators"}, {"seed": 16, "team_name": "Lehigh"}, {"seed": 16, "team_name": "Prairie View A&M"},
        {"seed": 8, "team_name": "Clemson Tigers"}, {"seed": 9, "team_name": "Iowa Hawkeyes"},
        {"seed": 5, "team_name": "Vanderbilt Commodores"}, {"seed": 12, "team_name": "McNeese Cowboys"},
        {"seed": 4, "team_name": "Nebraska Cornhuskers"}, {"seed": 13, "team_name": "Troy Trojans"},
        {"seed": 6, "team_name": "North Carolina Tar Heels"}, {"seed": 11, "team_name": "VCU Rams"},
        {"seed": 3, "team_name": "Illinois Fighting Illini"}, {"seed": 14, "team_name": "Penn Quakers"},
        {"seed": 7, "team_name": "Saint Mary's Gaels"}, {"seed": 10, "team_name": "Texas A&M Aggies"},
        {"seed": 2, "team_name": "Houston Cougars"}, {"seed": 15, "team_name": "Idaho Vandals"}
    ],
    "West": [
        {"seed": 1, "team_name": "Arizona Wildcats"}, {"seed": 16, "team_name": "Long Island Sharks"},
        {"seed": 8, "team_name": "Villanova Wildcats"}, {"seed": 9, "team_name": "Utah State Aggies"},
        {"seed": 5, "team_name": "Wisconsin Badgers"}, {"seed": 12, "team_name": "High Point Panthers"},
        {"seed": 4, "team_name": "Arkansas Razorbacks"}, {"seed": 13, "team_name": "Hawaii Rainbow Warriors"},
        {"seed": 6, "team_name": "BYU Cougars"}, {"seed": 11, "team_name": "NC State"}, {"seed": 11, "team_name": "Texas"},
        {"seed": 3, "team_name": "Gonzaga Bulldogs"}, {"seed": 14, "team_name": "Kennesaw State Owls"},
        {"seed": 7, "team_name": "Miami (FL) Hurricanes"}, {"seed": 10, "team_name": "Missouri Tigers"},
        {"seed": 2, "team_name": "Purdue Boilermakers"}, {"seed": 15, "team_name": "Queens (N.C.) Royals"}
    ],
    "Midwest": [
        {"seed": 1, "team_name": "Michigan Wolverines"}, {"seed": 16, "team_name": "Howard"}, {"seed": 16, "team_name": "UMBC"},
        {"seed": 8, "team_name": "Georgia Bulldogs"}, {"seed": 9, "team_name": "Saint Louis Billikens"},
        {"seed": 5, "team_name": "Texas Tech Red Raiders"}, {"seed": 12, "team_name": "Akron Zips"},
        {"seed": 4, "team_name": "Alabama Crimson Tide"}, {"seed": 13, "team_name": "Hofstra Pride"},
        {"seed": 6, "team_name": "Tennessee Volunteers"}, {"seed": 11, "team_name": "SMU"}, {"seed": 11, "team_name": "Miami (OH)"},
        {"seed": 3, "team_name": "Virginia Cavaliers"}, {"seed": 14, "team_name": "Wright State Raiders"},
        {"seed": 7, "team_name": "Kentucky Wildcats"}, {"seed": 10, "team_name": "Santa Clara Broncos"},
        {"seed": 2, "team_name": "Iowa State Cyclones"}, {"seed": 15, "team_name": "Tennessee State Tigers"}
    ]
}
