
import sys
import os

# Add path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.nfl_model import NFLModel

def run_nfl_analysis():
    print("--- Starting NFL Model Analysis ---")
    model = NFLModel()
    
    # 1. Fetch Edges
    print("Fetching live odds and calculating edges...")
    edges = model.find_edges()
    
    print(f"\nFound {len(edges)} potential plays.")
    
    if not edges:
        print("No edges found. Check if odds API is returning data.")
        return

    # 2. Sort by eV (Edge Value) - assuming 'edge' in dict is prob diff or point diff?
    # Inspecting nfl_model: "edge" is abs(fair_spread - market_spread) [Point Edge]
    # We want to print detail.
    
    # Sort by point edge descending
    edges.sort(key=lambda x: x.get('edge', 0), reverse=True)
    
    print("\n--- TOP NFL EDGES FOR TONIGHT ---")
    for e in edges:
        # Expected structure from nfl_model.find_edges might vary, checking find_edges implementation...
        # It's likely returning list of dicts.
        
        fmt = e.get('market_line', 0)
        fair = e.get('fair_line', 0)
        edge = e.get('edge', 0)
        
        home = e.get('home_team', 'Unknown')
        away = e.get('away_team', 'Unknown')
        bet = e.get('bet_on', 'Unknown')
        
        print(f"Matchup: {home} vs {away}")
        print(f"  Bet On: {bet} | Odds: {e.get('odds')}")
        print(f"  Market: {fmt} | Fair: {fair}")
        print(f"  Edge: {edge:.2f} pts")
        
        # If possible, print more info
        print("-" * 30)

if __name__ == "__main__":
    run_nfl_analysis()
