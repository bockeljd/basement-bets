
import os
import sys
import json
import math
import random
import statistics
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.getcwd())

from src.database import get_db_connection, _exec
from src.utils.naming import standardize_team_name
from src.services.kenpom_client import KenPomClient

def main():
    print("🚀 Starting 10,000-run Monte Carlo Simulations for 2026 March Madness...")
    
    matchups_path = "data/tournament_matchups_2026.json"
    if not os.path.exists(matchups_path):
        print(f"Error: {matchups_path} not found.")
        return

    with open(matchups_path, "r") as f:
        matchups = json.load(f)
        
    kp_client = KenPomClient()
    results = {}
    
    simulations = 10000
    league_avg_eff = 106.0 # 2025-26 D1 average estimate
    
    for region, games in matchups.items():
        print(f"\n--- {region} Region ---")
        results[region] = []
        
        for home_name, away_name in games:
            # Handle play-ins
            effective_home = home_name.split(" / ")[0].split(" - ")[0]
            effective_away = away_name.split(" / ")[0].split(" - ")[0]
            
            sh = standardize_team_name(effective_home)
            sa = standardize_team_name(effective_away)
            
            print(f"Simulating: {effective_away} @ {effective_home}...", end=" ", flush=True)
            
            try:
                # 1. Fetch KenPom Ratings
                h_ratings = kp_client.get_team_rating(sh)
                a_ratings = kp_client.get_team_rating(sa)
                
                if not h_ratings or not a_ratings:
                    print(f"MISSING DATA ({sh if not h_ratings else sa})", end=" ")
                    # Fallback to defaults
                    home_proj = 72.5
                    away_proj = 72.5
                    sigma_spread = 10.5
                else:
                    # 2. Interaction Formula
                    # Proj_Eff = Off_Eff + Def_Eff - League_Avg_Eff
                    h_eff = h_ratings['adj_o'] + a_ratings['adj_d'] - league_avg_eff
                    a_eff = a_ratings['adj_o'] + h_ratings['adj_d'] - league_avg_eff
                    
                    avg_tempo = (h_ratings['adj_t'] + a_ratings['adj_t']) / 2.0
                    
                    home_proj = (h_eff / 100.0) * avg_tempo
                    away_proj = (a_eff / 100.0) * avg_tempo
                    sigma_spread = 10.5 # Core CBB volatility

                # 3. Monte Carlo Trial
                team_vol = sigma_spread / 1.4142
                h_wins = 0
                h_scores = []
                a_scores = []
                
                for _ in range(simulations):
                    h_score = max(0, random.gauss(home_proj, team_vol))
                    a_score = max(0, random.gauss(away_proj, team_vol))
                    h_scores.append(h_score)
                    a_scores.append(a_score)
                    if h_score > a_score:
                        h_wins += 1
                    elif h_score == a_score:
                        h_wins += 0.5
                        
                # 4. Aggregate
                win_prob_h = (h_wins / simulations) * 100
                win_prob_a = 100 - win_prob_h
                fair_spread = -(statistics.mean(h_scores) - statistics.mean(a_scores))
                fair_total = statistics.mean(h_scores) + statistics.mean(a_scores)
                
                winner = home_name if win_prob_h >= win_prob_a else away_name
                
                print(f"DONE. {winner} Win% {max(win_prob_h, win_prob_a):.1f}% | Line {fair_spread:+.1f} | Tot {fair_total:.1f}")
                
                results[region].append({
                    "team_a": home_name,
                    "team_b": away_name,
                    "spread": round(fair_spread, 2),
                    "total": round(fair_total, 2),
                    "win_prob_a": round(win_prob_h, 1),
                    "win_prob_b": round(win_prob_a, 1),
                    "winner": winner,
                    "summary": f"MC Simulations: {simulations} | Sigma: {sigma_spread:.1f}"
                })
                
            except Exception as e:
                print(f"ERROR: {e}")
                
    # Save results
    output_path = "data/tournament_predictions_2026.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\n✅ All 64-game MC simulations completed. Results saved to {output_path}")

if __name__ == "__main__":
    main()
