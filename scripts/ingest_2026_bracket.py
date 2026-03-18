import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.database import get_db_connection, _exec
from src.services.ncaam_bracket_seed_loader import load_manual_bracket_seeds


def ingest_seeds():
    print("Ingesting 2026 Tournament Seeds...")
    seeds = load_manual_bracket_seeds()
    if not seeds:
        print("No manual bracket seeds available for 2026.")
        return

    with get_db_connection() as conn:
        # Clear old seeds for this season if any
        _exec(conn, "DELETE FROM ncaam_tournament_seeds WHERE season = '2025-26'")
        
        for region, teams in seeds.items():
            for entry in teams:
                seed = entry['seed']
                team = entry['team_name']
                print(f"  {region} Seed {seed}: {team}")
                _exec(conn, """
                    INSERT INTO ncaam_tournament_seeds (team_name, seed, region, season)
                    VALUES (%s, %s, %s, %s)
                """, (team, seed, region, '2025-26'))
        
        conn.commit()
    print("Ingestion complete.")


if __name__ == "__main__":
    ingest_seeds()
