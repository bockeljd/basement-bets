
import sys
import os

# Add src to path
sys.path.append(os.path.abspath('src'))

try:
    print("Importing NFLModel...")
    from src.models.nfl_model import NFLModel
    print("Instantiating NFLModel...")
    nfl = NFLModel()
    print("Running NFLModel...")
    edges = nfl.find_edges()
    actionable = [e for e in edges if e.get('is_actionable')]
    print(f"NFL Edges Found: {len(actionable)} Actionable / {len(edges)} Total")
except Exception as e:
    print(f"NFL FAILED: {e}")
    import traceback
    traceback.print_exc()

try:
    print("Importing NCAAMModel...")
    from src.models.ncaam_model import NCAAMModel
    print("Instantiating NCAAMModel...")
    ncaam = NCAAMModel()
    print("Running NCAAMModel...")
    # Inspect internal state
    if not ncaam.team_stats:
        ncaam.fetch_data()
    
    print(f"Stats Loaded: {len(ncaam.team_stats)} teams.")
    print(f"Sample Stats Keys: {list(ncaam.team_stats.keys())[:5]}")
    
    odds = ncaam.odds_client.get_odds('basketball_ncaab', markets='totals')
    if odds:
        print(f"Sample Odds Team: {odds[0]['home_team']} vs {odds[0]['away_team']}")
        
    edges = ncaam.find_edges()
    actionable = [e for e in edges if e.get('is_actionable')]
    print(f"NCAAM Edges Found: {len(actionable)} Actionable / {len(edges)} Total")
except Exception as e:
    print(f"NCAAM FAILED: {e}")
    import traceback
    traceback.print_exc()
