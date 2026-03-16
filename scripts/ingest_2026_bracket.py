
import os
import sys
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from src.database import get_db_connection, _exec

BRACKET_DATA = {
    "East": [
        (1, "Duke Blue Devils"), (16, "Siena Saints"),
        (8, "Ohio State Buckeyes"), (9, "TCU Horned Frogs"),
        (5, "St. John's Red Storm"), (12, "Northern Iowa Panthers"),
        (4, "Kansas Jayhawks"), (13, "Cal Baptist Lancers"),
        (6, "Louisville Cardinals"), (11, "South Florida Bulls"),
        (3, "Michigan State Spartans"), (14, "North Dakota State Bison"),
        (7, "UCLA Bruins"), (10, "UCF Knights"),
        (2, "UConn Huskies"), (15, "Furman Paladins")
    ],
    "South": [
        (1, "Florida Gators"), (16, "Lehigh / Prairie View A&M"),
        (8, "Clemson Tigers"), (9, "Iowa Hawkeyes"),
        (5, "Vanderbilt Commodores"), (12, "McNeese Cowboys"),
        (4, "Nebraska Cornhuskers"), (13, "Troy Trojans"),
        (6, "North Carolina Tar Heels"), (11, "VCU Rams"),
        (3, "Illinois Fighting Illini"), (14, "Penn Quakers"),
        (7, "Saint Mary's Gaels"), (10, "Texas A&M Aggies"),
        (2, "Houston Cougars"), (15, "Idaho Vandals")
    ],
    "West": [
        (1, "Arizona Wildcats"), (16, "Long Island Sharks"),
        (8, "Villanova Wildcats"), (9, "Utah State Aggies"),
        (5, "Wisconsin Badgers"), (12, "High Point Panthers"),
        (4, "Arkansas Razorbacks"), (13, "Hawaii Rainbow Warriors"),
        (6, "BYU Cougars"), (11, "NC State / Texas"),
        (3, "Gonzaga Bulldogs"), (14, "Kennesaw State Owls"),
        (7, "Miami (FL) Hurricanes"), (10, "Missouri Tigers"),
        (2, "Purdue Boilermakers"), (15, "Queens (N.C.) Royals")
    ],
    "Midwest": [
        (1, "Michigan Wolverines"), (16, "Howard / UMBC"),
        (8, "Georgia Bulldogs"), (9, "Saint Louis Billikens"),
        (5, "Texas Tech Red Raiders"), (12, "Akron Zips"),
        (4, "Alabama Crimson Tide"), (13, "Hofstra Pride"),
        (6, "Tennessee Volunteers"), (11, "SMU / Miami (OH)"),
        (3, "Virginia Cavaliers"), (14, "Wright State Raiders"),
        (7, "Kentucky Wildcats"), (10, "Santa Clara Broncos"),
        (2, "Iowa State Cyclones"), (15, "Tennessee State Tigers")
    ]
}

def ingest_seeds():
    print("Ingesting 2026 Tournament Seeds...")
    with get_db_connection() as conn:
        # Clear old seeds for this season if any
        _exec(conn, "DELETE FROM ncaam_tournament_seeds WHERE season = '2025-26'")
        
        for region, teams in BRACKET_DATA.items():
            for seed, team in teams:
                print(f"  {region} Seed {seed}: {team}")
                _exec(conn, """
                    INSERT INTO ncaam_tournament_seeds (team_name, seed, region, season)
                    VALUES (%s, %s, %s, %s)
                """, (team, seed, region, '2025-26'))
        
        conn.commit()
    print("Ingestion complete.")

if __name__ == "__main__":
    ingest_seeds()
