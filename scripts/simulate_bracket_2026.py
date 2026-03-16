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
import random
import statistics

sys.path.append(os.getcwd())

from src.database import get_db_connection, _exec
from src.utils.naming import standardize_team_name
from src.services.kenpom_client import KenPomClient

SIMULATIONS = 10000
LEAGUE_AVG_EFF = 106.0  # 2025-26 D1 average
SIGMA = 10.5             # Core CBB game-to-game volatility

_kp_cache = {}

def get_ratings(kp_client, team_name):
    """Fetch KenPom ratings with in-memory caching."""
    key = standardize_team_name(team_name)
    if key not in _kp_cache:
        _kp_cache[key] = kp_client.get_team_rating(key)
    return _kp_cache[key]

def simulate_game(kp_client, team_a_raw, team_b_raw, neutral=True):
    """
    Simulate a single game using the KenPom Interaction Formula + Monte Carlo.
    Returns a dict with all simulation output.
    """
    # Strip play-in variants (e.g. "Howard / UMBC" -> "Howard")
    team_a_raw = team_a_raw.split(" / ")[0].split(" - ")[0].strip()
    team_b_raw = team_b_raw.split(" / ")[0].split(" - ")[0].strip()

    a_ratings = get_ratings(kp_client, team_a_raw)
    b_ratings = get_ratings(kp_client, team_b_raw)

    if not a_ratings or not b_ratings:
        missing = team_a_raw if not a_ratings else team_b_raw
        print(f"    ⚠️  MISSING DATA for {missing} — using 50/50 coin flip")
        home_proj = 72.5
        away_proj = 72.5
    else:
        h_eff = a_ratings['adj_o'] + b_ratings['adj_d'] - LEAGUE_AVG_EFF
        a_eff = b_ratings['adj_o'] + a_ratings['adj_d'] - LEAGUE_AVG_EFF
        avg_tempo = (a_ratings['adj_t'] + b_ratings['adj_t']) / 2.0
        home_proj = (h_eff / 100.0) * avg_tempo
        away_proj = (a_eff / 100.0) * avg_tempo

    team_vol = SIGMA / 1.4142
    h_wins = 0
    h_scores = []
    a_scores = []

    for _ in range(SIMULATIONS):
        h = max(0, random.gauss(home_proj, team_vol))
        a = max(0, random.gauss(away_proj, team_vol))
        h_scores.append(h)
        a_scores.append(a)
        if h > a:
            h_wins += 1
        elif h == a:
            h_wins += 0.5

    win_prob_a = (h_wins / SIMULATIONS) * 100
    win_prob_b = 100 - win_prob_a
    fair_spread = -(statistics.mean(h_scores) - statistics.mean(a_scores))
    fair_total = statistics.mean(h_scores) + statistics.mean(a_scores)
    winner = team_a_raw if win_prob_a >= win_prob_b else team_b_raw

    return {
        "team_a": team_a_raw,
        "team_b": team_b_raw,
        "spread": round(fair_spread, 2),
        "total": round(fair_total, 2),
        "win_prob_a": round(win_prob_a, 1),
        "win_prob_b": round(win_prob_b, 1),
        "winner": winner,
        "summary": f"MC:{SIMULATIONS} | σ:{SIGMA}"
    }

def simulate_round(kp_client, matchups, round_name):
    """Simulate all games in a round. matchups is a list of (team_a, team_b) tuples."""
    results = []
    print(f"\n  ── {round_name} ──")
    for team_a, team_b in matchups:
        print(f"  {team_a} vs {team_b}...", end=" ", flush=True)
        result = simulate_game(kp_client, team_a, team_b)
        print(f"{result['winner']} ({max(result['win_prob_a'], result['win_prob_b']):.1f}%)")
        results.append(result)
    return results

def pair_winners(results):
    """Pair up winners from one round to create the next round's matchups."""
    winners = [r['winner'] for r in results]
    return [(winners[i], winners[i+1]) for i in range(0, len(winners), 2)]

def main():
    print("🏆 2026 March Madness Full Bracket Simulation (10,000 MC trials/game)")
    print("=" * 64)

    matchups_path = "data/tournament_matchups_2026.json"
    with open(matchups_path) as f:
        matchups = json.load(f)

    kp = KenPomClient()
    region_names = ["East", "South", "West", "Midwest"]

    output = {
        "season": "2025-26",
        "rounds": {},
        "final_four": [],
        "championship": None,
        "champion": None
    }

    regional_winners = {}  # region -> winner who advances to Final Four

    # ── ROUNDS 1-4: Within each region ──
    for region in region_names:
        print(f"\n{'='*40}\n🌎 {region} Region\n{'='*40}")

        # Round of 64
        r64_matchups = [(a, b) for a, b in matchups[region]]
        r64_results = simulate_round(kp, r64_matchups, f"{region} – Round of 64")

        # Round of 32
        r32_pairs = pair_winners(r64_results)
        r32_results = simulate_round(kp, r32_pairs, f"{region} – Round of 32")

        # Sweet 16
        sw16_pairs = pair_winners(r32_results)
        sw16_results = simulate_round(kp, sw16_pairs, f"{region} – Sweet 16")

        # Elite 8
        e8_pairs = pair_winners(sw16_results)
        e8_results = simulate_round(kp, e8_pairs, f"{region} – Elite 8")

        regional_winner = e8_results[0]['winner']
        regional_winners[region] = regional_winner
        print(f"\n  🏅 {region} Regional Champion: {regional_winner}")

        output["rounds"][region] = {
            "round_of_64": r64_results,
            "round_of_32": r32_results,
            "sweet_16": sw16_results,
            "elite_8": e8_results
        }

    # ── FINAL FOUR ──
    print(f"\n{'='*40}\n🏟️  Final Four\n{'='*40}")
    # Traditional bracket: East vs West, South vs Midwest
    ff_matchups = [
        (regional_winners["East"], regional_winners["West"]),
        (regional_winners["South"], regional_winners["Midwest"])
    ]
    ff_results = simulate_round(kp, ff_matchups, "Final Four")
    output["final_four"] = ff_results

    # ── CHAMPIONSHIP ──
    print(f"\n{'='*40}\n🥇 National Championship\n{'='*40}")
    champ_matchup = [(ff_results[0]['winner'], ff_results[1]['winner'])]
    champ_results = simulate_round(kp, champ_matchup, "Championship")
    output["championship"] = champ_results[0]
    output["champion"] = champ_results[0]['winner']

    print(f"\n\n🏆 2026 NATIONAL CHAMPION: {output['champion']} 🏆")

    # Save output
    out_path = "data/tournament_predictions_2026.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Full bracket simulation complete. Saved to {out_path}")

if __name__ == "__main__":
    main()
