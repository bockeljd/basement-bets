
import os
import sys
import json
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.getcwd())

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.database import get_db_connection, _exec
from src.utils.naming import standardize_team_name

def main():
    print("Generating Model Projections for 2026 March Madness Bracket (DRY RUN)...")
    
    with open("data/tournament_matchups_2026.json", "r") as f:
        matchups = json.load(f)
        
    model = NCAAMMarketFirstModelV2()
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
                
                # Manual event context to avoidnaive/aware errors and DB requirements
                event_context = {
                    "id": game_id,
                    "home_team": standardize_team_name(effective_home),
                    "away_team": standardize_team_name(effective_away),
                    "sport": "NCAAM",
                    "league": "NCAAM",
                    "start_time": datetime.now(timezone.utc),
                    "neutral_site": True
                }
                
                # Manual market snapshot
                market_snapshot = {
                    "total": 145.0,
                    "spread_home": 0.0,
                    "spread_price_home": -110,
                    "total_over_price": -110,
                    "_raw_snaps": []
                }
                
                # RUN ANALYSIS (persist=False to avoid Event ID dependency)
                prediction = model.analyze(
                    event_id=game_id,
                    market_snapshot=market_snapshot,
                    event_context=event_context,
                    persist=False
                )
                
                if "error" in prediction:
                    print(f"FAILED: {prediction['error']}")
                    continue
                    
                # Extract key metrics
                proj_spread = prediction.get("mu_spread_final", 0.0)
                proj_total = prediction.get("mu_total_final", 145.0)
                conf = prediction.get("confidence_score", 0.0)
                
                print(f"DONE. Home {proj_spread:+.1f} | Total {proj_total:.1f}")
                
                results[region].append({
                    "home": home_name,
                    "away": away_name,
                    "projected_spread": proj_spread,
                    "projected_total": proj_total,
                    "confidence": conf,
                    "prediction": prediction
                })
                
            except Exception as e:
                print(f"ERROR: {e}")
                
    # Save results
    output_path = "data/tournament_predictions_2026.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nAll projections saved to {output_path}")

if __name__ == "__main__":
    main()
