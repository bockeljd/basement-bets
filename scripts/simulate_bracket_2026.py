"""
simulate_bracket_2026.py
Full 6-round March Madness 2026 bracket simulation using KenPom Interaction Formula
and 10,000 Monte Carlo trials per game.

Rounds: Round of 64 → 32 → Sweet 16 → Elite 8 → Final Four → Championship
Output: data/tournament_predictions_2026.json
"""

import os
import sys
import json
from datetime import datetime

sys.path.append(os.getcwd())

from src.services.bracket_simulator import LiveBracketSimulator

def convert_matchups_to_seeds(matchups_by_region):
    """
    Converts a list of R64 (team_a, team_b) tuples per region back into a 
    standardized seed assignment so `simulate_bracket` can parse it.
    Matches standard order: (1,16), (8,9), (5,12), (4,13), (6,11), (3,14), (7,10), (2,15)
    """
    seeds = {}
    pairing_order = [(1,16), (8,9), (5,12), (4,13), (6,11), (3,14), (7,10), (2,15)]
    
    for region, matches in matchups_by_region.items():
        region_seeds = []
        for i, (ta, tb) in enumerate(matches):
            if i < len(pairing_order):
                s1, s2 = pairing_order[i]
                region_seeds.append({"team_name": ta, "seed": s1})
                region_seeds.append({"team_name": tb, "seed": s2})
        seeds[region] = region_seeds
    return seeds

def main():
    print("🏆 2026 March Madness Full Bracket Simulation (Canonical Service)")
    print("=" * 64)

    matchups_path = "data/tournament_matchups_2026.json"
    with open(matchups_path) as f:
        matchups = json.load(f)

    # 1. Convert rigid JSON to flexible seed mappings
    seeds = convert_matchups_to_seeds(matchups)
    
    # 2. Run Canonical Simulator (MC 10000 built-in)
    sim = LiveBracketSimulator(simulations=10000)
    output = sim.simulate_full_bracket(seeds)

    print(f"\n\n🏆 2026 NATIONAL CHAMPION: {output.get('champion')} 🏆")

    # 3. Save output
    out_path = "data/tournament_predictions_2026.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Full bracket simulation complete. Saved to {out_path}")

if __name__ == "__main__":
    main()
