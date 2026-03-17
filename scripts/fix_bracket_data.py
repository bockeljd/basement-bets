
import os
import psycopg2
from src.database import get_admin_db_connection, _exec

def init_ncaam_tournament_seeds_db():
    schema = """
    CREATE TABLE IF NOT EXISTS ncaam_tournament_seeds (
        id SERIAL PRIMARY KEY,
        season TEXT NOT NULL,
        region TEXT NOT NULL,
        seed INTEGER NOT NULL,
        team_name TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_seeds_season_region_seed ON ncaam_tournament_seeds(season, region, seed);
    CREATE INDEX IF NOT EXISTS idx_seeds_season_region ON ncaam_tournament_seeds(season, region);
    """
    
    # Mock seeds for 2026 simulation
    regions = ["East", "South", "West", "Midwest"]
    # Using some top teams for 2026 feel
    teams = [
        "Duke", "Kansas", "Alabama", "UConn", 
        "Houston", "Purdue", "Arizona", "North Carolina",
        "Gonzaga", "Tennessee", "Iowa State", "Creighton",
        "Baylor", "Kentucky", "Marquette", "Illinois",
        "Michigan St.", "Auburn", "BYU", "Saint Mary's",
        "Wisconsin", "San Diego St.", "Florida Atlantic", "Texas",
        "Clemson", "Utah St.", "South Carolina", "Dayton",
        "Nevada", "Boise State", "Colorado", "Drake",
        "James Madison", "Grand Canyon", "Samford", "McNeese",
        "Yale", "Charleston", "Oakland", "Vermont",
        "Morehead St.", "Colgate", "South Dakota St.", "Stetson",
        "Longwood", "Saint Peter's", "Grambling St.", "Howard",
        "Montana St.", "Wagner", "Lehigh", "NC State",
        "Oregon", "Colorado St.", "Virginia", "Texas A&M",
        "New Mexico", "TCU", "Mississippi St.", "Northwestern",
        "Nebraska", "Washington St.", "St. John's", "Richmond"
    ]

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
            print("Table ncaam_tournament_seeds created.")
            
            # Populate
            for r_idx, region in enumerate(regions):
                for s in range(1, 17):
                    t_idx = (r_idx * 16) + (s - 1)
                    if t_idx < len(teams):
                        team_name = teams[t_idx]
                        cur.execute("""
                            INSERT INTO ncaam_tournament_seeds (season, region, seed, team_name)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (season, region, seed) DO UPDATE SET team_name = EXCLUDED.team_name
                        """, ("2025-26", region, s, team_name))
            
        conn.commit()
    print("Seeds populated for 2026 simulation.")

if __name__ == "__main__":
    init_ncaam_tournament_seeds_db()
