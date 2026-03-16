
import json
import os
import time
from fastapi import APIRouter, HTTPException, Request
from src.database import get_db_connection, _exec
from src.services.bracket_simulator import LiveBracketSimulator, SimulatorDataError
from src.utils.naming import standardize_team_name

router = APIRouter()

# Simple in-memory cache for simulation results
# key: "2026_bracket", value: {"data": {...}, "expiry": timestamp}
_SIM_CACHE = {}
CACHE_TTL = 3600  # 1 hour

@router.get("/api/ncaam/bracket/2026")
async def get_2026_bracket(request: Request, refresh: bool = False):
    """Return the full 2026 bracket structure with real-time simulations."""
    try:
        current_time = time.time()
        
        # 1. Check Cache
        if not refresh and "2026_bracket" in _SIM_CACHE:
            entry = _SIM_CACHE["2026_bracket"]
            if current_time < entry["expiry"]:
                return entry["data"]

        # 2. Run Live Simulation
        simulator = LiveBracketSimulator(simulations=10000)
        
        # Fetch seeds for simulation
        seeds_by_region = simulator.get_seeds_from_db()
        if not seeds_by_region:
            raise HTTPException(status_code=404, detail="Tournament seeds not found for 2026.")
            
        try:
            projections = simulator.simulate_full_bracket(seeds_by_region)
        except SimulatorDataError as e:
            # ZERO SILENT FALLBACKS
            raise HTTPException(status_code=500, detail=str(e))

        # 3. Create a lookup for seeds for UI enrichment
        seed_lookup = {}
        for region, seeds in seeds_by_region.items():
            for s in seeds:
                name = standardize_team_name(s['team_name'])
                seed_lookup[name] = s['seed']

        def enrich_matchups(matchup_list):
            """Add seed info to a list of matchup dicts."""
            enriched = []
            for m in (matchup_list or []):
                m = dict(m)
                m['seed_a'] = seed_lookup.get(standardize_team_name(m.get('team_a', '')))
                m['seed_b'] = seed_lookup.get(standardize_team_name(m.get('team_b', '')))
                enriched.append(m)
            return enriched

        # 4. Combine - Build enriched bracket data
        bracket_data = {
            "season": "2025-26",
            "champion": projections.get("champion"),
            "championship": projections.get("championship"),
            "final_four": enrich_matchups(projections.get("final_four", [])),
            "regions": {},
            "v": 4  # Version bump for live simulator
        }

        for region in ["East", "South", "West", "Midwest"]:
            reg_seeds = seeds_by_region.get(region, [])
            reg_rounds = projections.get("rounds", {}).get(region, {})
            
            bracket_data["regions"][region] = {
                "seeds": reg_seeds,
                "round_of_64": enrich_matchups(reg_rounds.get("round_of_64", [])),
                "round_of_32": enrich_matchups(reg_rounds.get("round_of_32", [])),
                "sweet_16": enrich_matchups(reg_rounds.get("sweet_16", [])),
                "elite_8": enrich_matchups(reg_rounds.get("elite_8", [])),
            }
            
        # Update Cache
        _SIM_CACHE["2026_bracket"] = {
            "data": bracket_data,
            "expiry": current_time + CACHE_TTL
        }
            
        return bracket_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[bracket-api] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
