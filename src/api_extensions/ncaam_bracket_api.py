
import json
import os
import time
from fastapi import APIRouter, HTTPException, Request
from src.database import get_db_connection, _exec
from src.services.bracket_simulator import LiveBracketSimulator, SimulatorDataError
from src.utils.naming import standardize_team_name

router = APIRouter()

# Local memory cache for ultra-fast hits (10s TTL)
_LOCAL_CACHE = {"data": None, "expiry": 0}
LOCAL_TTL = 10

def _get_db_cache():
    """Fetch simulation from ncaam_bracket_cache table."""
    try:
        with get_db_connection() as conn:
            row = _exec(conn, "SELECT data_json FROM ncaam_bracket_cache WHERE season = '2025-26'").fetchone()
            if row:
                return row['data_json']
    except Exception as e:
        print(f"[bracket-api] Cache read error: {e}")
    return None

def _save_db_cache(data):
    """Save simulation to ncaam_bracket_cache table."""
    try:
        with get_db_connection() as conn:
            _exec(conn, """
                INSERT INTO ncaam_bracket_cache (season, data_json, updated_at)
                VALUES ('2025-26', %s, NOW())
                ON CONFLICT (season) DO UPDATE SET data_json = EXCLUDED.data_json, updated_at = NOW()
            """, (json.dumps(data),))
            conn.commit()
            print("[bracket-api] Cache persisted to DB.")
    except Exception as e:
        print(f"[bracket-api] Cache write error: {e}")

@router.get("/api/ncaam/bracket/2026/debug")
async def get_bracket_debug(request: Request):
    """Internal debug endpoint for bracket prediction health."""
    db_cache = _get_db_cache()
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    return {
        "status": "healthy",
        "model_version": NCAAMMarketFirstModelV2.VERSION,
        "local_cache": {
            "active": _LOCAL_CACHE["data"] is not None,
            "expiry": _LOCAL_CACHE["expiry"],
            "remaining": max(0, int(_LOCAL_CACHE["expiry"] - time.time()))
        },
        "db_cache": {
            "present": db_cache is not None,
            "size": len(json.dumps(db_cache)) if db_cache else 0
        },
        "system_time": time.time()
    }

@router.post("/api/ncaam/bracket/2026/recompute")
async def recompute_bracket(request: Request):
    """Force re-run the simulation and update the DB cache."""
    return await get_2026_bracket(request, refresh=True)

@router.get("/api/ncaam/bracket/2026")
async def get_2026_bracket(request: Request, refresh: bool = False):
    """Return the full 2026 bracket structure with real-time or cached simulations."""
    current_time = time.time()
    
    # 1. Local Memory Cache (Fastest)
    if not refresh and _LOCAL_CACHE["data"] and current_time < _LOCAL_CACHE["expiry"]:
        return _LOCAL_CACHE["data"]

    # 2. DB Cache (Faster than simulation)
    if not refresh:
        cached = _get_db_cache()
        if cached:
            _LOCAL_CACHE["data"] = cached
            _LOCAL_CACHE["expiry"] = current_time + LOCAL_TTL
            return cached

    # 3. Live Simulation (Compute)
    print("[bracket-api] Cache miss or refresh requested. Starting simulation...")
    try:
        from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService
        service = NCAAMTournamentPredictionService()
        simulator = LiveBracketSimulator(simulations=2500)
        seeds_by_region = simulator.get_seeds_from_db()
        
        if not seeds_by_region:
            raise HTTPException(status_code=404, detail="Tournament seeds not found for 2026.")
            
        projections = service.simulate_bracket(seeds_by_region, simulations=2500)
        bracket_data = projections.model_dump()
        bracket_data["v"] = "5-canonical-cached"
        
        # Build seed lookup for UI enrichment
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
            
        bracket_data["first_four"] = enrich_matchups(bracket_data.get("first_four", []))
        bracket_data["final_four"] = enrich_matchups(bracket_data.get("final_four", []))
        if bracket_data.get("championship"):
            enrich_matchups([bracket_data["championship"]])
            
        for region, rounds_dict in bracket_data.get("regions", {}).items():
            for round_name, matchups_list in rounds_dict.items():
                rounds_dict[round_name] = enrich_matchups(matchups_list)
            rounds_dict["seeds"] = seeds_by_region.get(region, [])

        # 4. Save to DB Cache & Local Cache
        _save_db_cache(bracket_data)
        _LOCAL_CACHE["data"] = bracket_data
        _LOCAL_CACHE["expiry"] = current_time + LOCAL_TTL
            
        return bracket_data
        
    except Exception as e:
        print(f"[bracket-api] Fatal Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
