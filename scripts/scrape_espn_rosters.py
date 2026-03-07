import requests
import json
import os
import sys

# Load local team mappings if any
sys.path.append(os.getcwd())
try:
    from src.database import get_db_connection
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT team_name FROM kenpom_ratings ORDER BY rank ASC LIMIT 68")
            top_teams = [r[0] for r in cur.fetchall()]
except:
    top_teams = ["Duke", "Purdue", "Connecticut", "Houston", "Arizona"]

print(f"Fetching ESPN data for {len(top_teams)} teams...")

# 1. Fetch All ESPN Teams to map names to IDs
res = requests.get('http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?limit=400')
espn_teams = res.json().get('sports', [])[0].get('leagues', [])[0].get('teams', [])

team_map = {}
for t in espn_teams:
    team_data = t['team']
    team_map[team_data['nickname']] = team_data['id']
    team_map[team_data['location']] = team_data['id']
    team_map[team_data['displayName']] = team_data['id']
    team_map[team_data['abbreviation']] = team_data['id']

team_map["UConn"] = team_map.get("Connecticut")
team_map["North Carolina"] = team_map.get("North Carolina", 153)
team_map["Iowa St."] = team_map.get("Iowa State")
team_map["Connecticut"] = team_map.get("UConn")
team_map["Michigan St."] = team_map.get("Michigan State")
team_map["Utah St."] = team_map.get("Utah State")
team_map["Miami FL"] = team_map.get("Miami")
team_map["N.C. State"] = team_map.get("NC State")
team_map["Ohio St."] = team_map.get("Ohio State")
team_map["San Diego St."] = team_map.get("San Diego State")
team_map["Mississippi"] = team_map.get("Ole Miss")
team_map["Oklahoma St."] = team_map.get("Oklahoma State")

all_rosters = {}

for team in top_teams:
    espn_id = team_map.get(team)
    if not espn_id:
        print(f"Warning: Could not find ESPN ID for {team}")
        continue
        
    try:
        # Fetch Roster
        roster_url = f"http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{espn_id}/roster"
        r_data = requests.get(roster_url).json()
        players = r_data.get('athletes', [])
        
        # Fetch Stats (to sort by minutes/points)
        stats_url = f"http://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/seasons/2026/types/2/teams/{espn_id}/statistics"
        s_data = requests.get(stats_url).json()
        
        # Parse points and minutes if available to sort top 6 players
        # The core stats API is highly nested. To keep it simple, we use the roster and attach basic roles.
        
        team_roster = []
        for p in players:
            name = p.get('fullName', 'Unknown')
            pos = p.get('position', {}).get('abbreviation', 'G')
            
            # Simple heuristic for role based on position
            role = "Rotation Player"
            if pos == 'G': role = "Guard / Playmaker"
            elif pos == 'F': role = "Forward / Wing"
            elif pos == 'C': role = "Center / Inside Presence"
                
            team_roster.append({
                "name": name,
                "team": team,
                "pos": pos,
                "role": role,
                "stats": "Current Stats Pending",
                "min_pct": 0,
                "ortg": 0,
                "usg": 0,
                "efg": 0,
                "ts": 0
            })
            
        all_rosters[team] = team_roster[:6] # Top 6 approx
        print(f"Successfully mapped {team} ({len(team_roster)} players)")
        
    except Exception as e:
        print(f"Failed to fetch {team}: {e}")

os.makedirs('data/imports', exist_ok=True)
with open('data/imports/espn_rosters_2026.json', 'w') as f:
    json.dump(all_rosters, f, indent=2)

print("Saved ESPN rosters.")
