
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.ncaam_model import NCAAMModel

def test_live_scan():
    print("Initializing Model...")
    model = NCAAMModel()
    
    # Reload stats just in case (though fetch_data does it)
    print("Loading Torvik Data...")
    model.fetch_data()
    print(f"Loaded {len(model.team_stats)} teams.")
    
    print("\nScanning Live Market...")
    edges = model.find_edges()
    
    print(f"\nFound {len(edges)} Edges:")
    for e in edges:
        print(f"[{e['game_id']}] {e['matchup']} : Bet {e['bet_on']} ({e['market']})")
        print(f"  Line: {e['line']} vs Model: {e['model_line']}")
        print(f"  Edge: {e['edge']} | EV: {e['ev']} | Book: {e['book']}")
        print("-" * 40)
        
    if not edges:
        from src.models.odds_client import OddsAPIClient
        client = OddsAPIClient()
        odds = client.get_odds("basketball_ncaab", regions="us", markets="spreads,totals")
        if odds:
            print("\n[DEBUG] Sample Game Bookmakers:")
            import json
            print(json.dumps(odds[0].get('bookmakers', []), indent=2))


if __name__ == "__main__":
    test_live_scan()
