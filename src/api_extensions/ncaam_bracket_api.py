
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

@router.get("/api/ncaam/bracket/2026/debug")
async def get_bracket_debug(request: Request):
    """Internal debug endpoint for bracket prediction health."""
    from src.api import _is_valid_base_key
    
    # Optional authorization, but good practice for debug hooks
    key = request.headers.get("X-BASEMENT-KEY")
    if key and not _is_valid_base_key(key):
        raise HTTPException(status_code=403, detail="Invalid Basement Key")
        
    cache_keys = list(_SIM_CACHE.keys())
    active_cache = "2026_bracket" in _SIM_CACHE
    
    time_remaining = 0
    if active_cache:
        time_remaining = max(0, _SIM_CACHE["2026_bracket"]["expiry"] - time.time())
        
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    return {
        "status": "healthy",
        "model_version": NCAAMMarketFirstModelV2.VERSION,
        "cache": {
            "active": active_cache,
            "keys_loaded": len(cache_keys),
            "ttl_remaining_seconds": int(time_remaining)
        },
        "system_time": time.time()
    }

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

        # 2. Run Live Simulation Canonical Service
        from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService
        service = NCAAMTournamentPredictionService()
        
        # Use 2,500 for fast response times while preserving simulation accuracy
        # 10,000 takes ~6s, risking Vercel function timeouts on cold starts.
        simulator = LiveBracketSimulator(simulations=2500)
        seeds_by_region = simulator.get_seeds_from_db()
        
        if not seeds_by_region:
            raise HTTPException(status_code=404, detail="Tournament seeds not found for 2026.")
            
        try:
            # Simulate bracket (returns TournamentBracketSimulation pydantic model)
            projections = service.simulate_bracket(seeds_by_region, simulations=2500)
        except SimulatorDataError as e:
            raise HTTPException(status_code=500, detail=str(e))

        # 3. Dump the canonical model and enrich with seeds for UI
        bracket_data = projections.model_dump()
        bracket_data["v"] = "5-canonical" # Mark as the new canonical API format
        
        # Build seed lookup
        seed_lookup = {}
        for region, seeds in seeds_by_region.items():
            for s in seeds:
                name = standardize_team_name(s['team_name'])
                seed_lookup[name] = s['seed']

        def enrich_matchups(matchups_list):
            for m in matchups_list:
                m['seed_a'] = seed_lookup.get(standardize_team_name(m.get('team_a', '')))
                m['seed_b'] = seed_lookup.get(standardize_team_name(m.get('team_b', '')))
            return matchups_list
            
        # Inject into lists
        bracket_data["first_four"] = enrich_matchups(bracket_data.get("first_four", []))
        bracket_data["final_four"] = enrich_matchups(bracket_data.get("final_four", []))
        if bracket_data.get("championship"):
            enrich_matchups([bracket_data["championship"]])
            
        for region, rounds_dict in bracket_data.get("regions", {}).items():
            for round_name, matchups_list in rounds_dict.items():
                rounds_dict[round_name] = enrich_matchups(matchups_list)
            # Inject flat seed array into region for the UI header rendering
            rounds_dict["seeds"] = seeds_by_region.get(region, [])

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
