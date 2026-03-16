
import json
import os
from fastapi import APIRouter, HTTPException, Request
from src.database import get_db_connection, _exec

router = APIRouter()

@router.get("/api/ncaam/bracket/2026")
async def get_2026_bracket(request: Request):
    """Return the full 2026 bracket structure with all rounds and champion prediction."""
    try:
        # 1. Fetch seeds from database
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
            
        # 2. Load pre-computed projections
        proj_path = "data/tournament_predictions_2026.json"
        projections = {}
        if os.path.exists(proj_path):
            with open(proj_path, "r") as f:
                projections = json.load(f)
        
        from src.utils.naming import standardize_team_name

        # Create a lookup for seeds
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

        # 3. Combine - Build enriched bracket data
        bracket_data = {
            "season": "2025-26",
            "champion": projections.get("champion"),
            "championship": projections.get("championship"),
            "final_four": enrich_matchups(projections.get("final_four", [])),
            "regions": {}
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
            
        return bracket_data
        
    except Exception as e:
        print(f"[bracket-api] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
