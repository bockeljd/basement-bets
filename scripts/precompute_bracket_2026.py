
import os
import sys
import json
import time

# Add project root to path
sys.path.append(os.getcwd())

from src.database import get_db_connection, _exec
from src.services.bracket_simulator import LiveBracketSimulator
from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService
from src.utils.naming import standardize_team_name

def precompute():
    print("Starting manual precompute of 2026 bracket...")
    service = NCAAMTournamentPredictionService()
    simulator = LiveBracketSimulator(simulations=2500)
    
    seeds_by_region = simulator.get_seeds_from_db()
    if not seeds_by_region:
        print("ERROR: No seeds found.")
        return

    print(f"Loaded {sum(len(l) for l in seeds_by_region.values())} teams. Simulating...")
    start = time.time()
    projections = service.simulate_bracket(seeds_by_region, simulations=2500)
    duration = time.time() - start
    print(f"Simulation completed in {duration:.2f}s.")
    
    bracket_data = projections.model_dump()
    bracket_data["v"] = "5-canonical-cached"
    
    # Enrichment
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

    # Save to DB
    print("Saving to DB cache...")
    with get_db_connection() as conn:
        _exec(conn, """
            INSERT INTO ncaam_bracket_cache (season, data_json, updated_at)
            VALUES ('2025-26', %s, NOW())
            ON CONFLICT (season) DO UPDATE SET data_json = EXCLUDED.data_json, updated_at = NOW()
        """, (json.dumps(bracket_data),))
        conn.commit()
    
    print("Success! Cache warmed.")

if __name__ == "__main__":
    precompute()
