import os
import sys
import json
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.getcwd())

from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService, TournamentGameInput
from src.utils.naming import standardize_team_name

def main():
    print("Generating Model Projections for 2026 March Madness Bracket (DRY RUN)...")
    
    with open("data/tournament_matchups_2026.json", "r") as f:
        matchups = json.load(f)
        
    service = NCAAMTournamentPredictionService()
    results = {}
    
    for region, games in matchups.items():
        print(f"\n--- {region} Region ---")
        results[region] = []
        
        for home_name, away_name in games:
            # Handle play-ins
            effective_home = home_name.split(" / ")[0]
            effective_away = away_name.split(" / ")[0]
            
            print(f"Analyzing: {effective_away} @ {effective_home}...", end=" ", flush=True)
            
            try:
                game_id = f"bracket:2026:{region}:{effective_home}:{effective_away}"
                
                # RUN ANALYSIS 
                prediction = service.predict_game(TournamentGameInput(
                    team_a=effective_home,
                    team_b=effective_away,
                    round_index=0,
                    region=region,
                    event_id=game_id,
                    neutral_site=True
                ))
                    
                # Extract key metrics
                proj_spread = prediction.projected_spread_a
                proj_total = prediction.projected_total
                conf = prediction.confidence_0_100
                
                print(f"DONE. Home {proj_spread:+.1f} | Total {proj_total:.1f}")
                
                results[region].append({
                    "home": home_name,
                    "away": away_name,
                    "projected_spread": proj_spread,
                    "projected_total": proj_total,
                    "confidence": conf,
                    "prediction": prediction.model_dump()
                })
                
            except Exception as e:
                print(f"ERROR: {e}")
                
    # Save results (using a distinct filename to avoid collision with simulate_bracket)
    output_path = "data/bracket_matchups_predictions_2026.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nAll projections saved to {output_path}")

if __name__ == "__main__":
    main()
