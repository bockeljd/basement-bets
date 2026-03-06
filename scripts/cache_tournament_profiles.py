#!/usr/bin/env python3
"""
Pre-caches rich LLM scouting profiles for top tournament teams.
Ensures the UI loads immediately without triggering timeouts.
"""

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec
from src.services.profile_generator import ProfileGeneratorService

def main():
    profiler = ProfileGeneratorService()
    
    # Let's seed the top 10 teams by KenPom rank
    print("[Cache Profiles] Fetching top 10 KenPom teams to seed...")
    with get_db_connection() as conn:
        krows = _exec(conn, """
            SELECT team_name, rank
            FROM kenpom_ratings
            ORDER BY rank ASC
            LIMIT 10
        """).fetchall()
        
    for idx, row in enumerate(krows):
        team = row['team_name']
        print(f"[{idx+1}/10] Generating profile for {team}...")
        try:
            # generate_profile handles caching internally
            prof = profiler.generate_profile(team)
            print(f"  -> Success! Generated {len(prof.get('players', []))} players and a narrative block.")
        except Exception as e:
            print(f"  -> Error for {team}: {e}")

if __name__ == "__main__":
    main()
