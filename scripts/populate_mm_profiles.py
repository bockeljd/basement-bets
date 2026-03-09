import os
import sys
import time
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec
from src.services.profile_generator import ProfileGeneratorService

def main():
    print(f"[{datetime.now().isoformat()}] Starting MM Profile Population (Top 80)")
    
    svc = ProfileGeneratorService()
    
    with get_db_connection() as conn:
        print("Fetching top 80 teams from KenPom...")
        rows = _exec(conn, """
            SELECT team_name, rank 
            FROM kenpom_ratings 
            ORDER BY rank ASC 
            LIMIT 80
        """).fetchall()
        
    teams = [r['team_name'] for r in rows]
    print(f"Found {len(teams)} teams. Beginning generation (best-effort)...")
    
    results = {"success": [], "failed": []}
    
    for i, team in enumerate(teams):
        print(f"[{i+1}/80] Processing {team}...", end=" ", flush=True)
        try:
            # force_refresh=True ensures we get fresh LLM insight if anything changed
            profile = svc.generate_profile(team, force_refresh=True)
            if profile:
                print("DONE.")
                results["success"].append(team)
            else:
                print("FAILED (empty profile).")
                results["failed"].append(team)
        except Exception as e:
            print(f"ERROR: {e}")
            results["failed"].append(team)
        
        # Polite delay to avoid rate limiting
        time.sleep(15.0)
        
    print(f"\n[{datetime.now().isoformat()}] MM Profile Population Complete.")
    print(f"Summary: {len(results['success'])} Success, {len(results['failed'])} Failed.")
    
    with open("data/mm_profile_population_report.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
