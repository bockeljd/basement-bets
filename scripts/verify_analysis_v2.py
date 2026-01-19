from src.services.game_analyzer import GameAnalyzer
from src.services.barttorvik import BartTorvikClient
import time

print("=== Verifying Analysis V2 (Projections) ===")

# 1. Fetch Official Projections directly to compare
client = BartTorvikClient()
projections = client.fetch_daily_projections()
if not projections:
    # Try fetching manual date if today is empty (late night?)
    # or just assume None
    print("Warning: No projections found for today.")
    match = None
    match_team = "Duke"
else:
    # Find a sample match
    keys = list(projections.keys())
    if keys:
        match_team = keys[0]
        match = projections[match_team]
        print(f"Sample Official Projection for {match_team}: {match}")
    else:
        match = None
        match_team = "Duke"

# 2. Run Analyzer
analyzer = GameAnalyzer()
if match:
    home = match['team'] if 'match' not in match else match['team'] # Structure varies
    # Actually fetch_daily_projections returns dict of team -> proj keys
    # Keys: opponent, total, projected_score, spread, raw_line
    
    # We need home/away.
    # If match_team is home...
    # The structure I implemented in barttorvik.py:
    # projections[away] = { ... "team": away, "opponent": home ... }
    # Let's just pick two teams from keys that play each other.
    
    home_team = match['team']
    away_team = match['opponent']
    
    print(f"\nAnalyzing {away_team} @ {home_team}...")
    
    res = analyzer.analyze("test_id", "NCAAM", home_team, away_team)
    
    print("\nRecommendations:")
    for rec in res['recommendations']:
        print(f" - {rec['bet_type']}: {rec['selection']} (Edge: {rec['edge']})")
        
    print(f"\nNarrative: {res['narrative'][:200]}...")
    
    # Check if spread matches official
    official_spread = match['spread'] 
    print(f"\nOfficial Spread from Torvik: {official_spread}")
    
    # We can't easily see internal calculations of Analyzer, but if Recommendations aligns, good.
    
else:
    print("No games found to verify against.")
