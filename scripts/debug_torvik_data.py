from src.services.barttorvik import BartTorvikClient
from src.models.ncaam_model import NCAAMModel
from src.services.game_analyzer import GameAnalyzer
import json

print("=== Debugging Bart Torvik Data Quality ===")

# 1. Inspect Raw Data
client = BartTorvikClient()
ratings = client.get_efficiency_ratings(year=2026)

print(f"\nFetched {len(ratings)} teams.")
if len(ratings) > 0:
    sample_key = list(ratings.keys())[0]
    print(f"Sample Team ({sample_key}): {ratings[sample_key]}")
    
    # Check for suspiciously flat 100.0 ratings
    flat_ratings = [t for t, d in ratings.items() if d['off_rating'] == 100.0 and d['def_rating'] == 100.0]
    print(f"Teams with exactly 100.0/100.0 ratings: {len(flat_ratings)}")

# 2. Test Fuzzy Matching
model = NCAAMModel()
test_teams = ["Vermont", "Albany", "UAlbany", "Duke", "North Carolina", "Kansas"]

print("\n=== Testing Fuzzy Matching ===")
for team in test_teams:
    stats = model.get_team_stats(team)
    if stats:
        print(f"'{team}' -> Found: Off={stats.get('eff_off')} Def={stats.get('eff_def')} Tempo={stats.get('tempo')}")
    else:
        print(f"'{team}' -> NOT FOUND")

# 2.5 Inspect Raw DB Row
from src.database import get_db_connection, _exec
print("\n=== Inspecting Raw DB Row for 'Vermont' ===")
with get_db_connection() as conn:
    row = _exec(conn, "SELECT * FROM bt_team_metrics_daily WHERE team_text LIKE '%Vermont%'").fetchone()
    if row:
        print(f"Raw Row: {dict(row)}")
    else:
        print("Raw Row: NOT FOUND")

# 3. Simulate Game Analysis
print("\n=== Simulating Game Analysis ===")
analyzer = GameAnalyzer()
# Vermont vs UAlbany (scheduled today)
res = analyzer.analyze("test_id", "NCAAM", "UAlbany Great Danes", "Vermont Catamounts")

print(f"\nNarrative: {res['narrative']}")
print("Recommendations:")
for rec in res['recommendations']:
    print(f" - {rec['bet_type']}: {rec['selection']} (Edge: {rec['edge']}, Conf: {rec['confidence']})")
