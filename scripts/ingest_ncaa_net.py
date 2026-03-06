#!/usr/bin/env python3
"""
Ingest NCAA NET Rankings into Database

Scrapes NCAA.com and saves NET rankings, records, and Quadrant splits.
"""

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.ncaa_net_client import NcaamNetClient
from src.database import get_db_connection, _exec

def ingest_ncaa_net():
    client = NcaamNetClient()
    print("[NCAAM NET] Fetching live HTML...")
    data = client.fetch()
    through_games, rows = client.parse(data['html'])
    
    if not rows:
        print("[ERROR] No teams scraped from NCAA NET")
        return
    
    print(f"[NCAAM NET] Scraped {len(rows)} teams. {through_games}")
    
    with get_db_connection() as conn:
        _exec(conn, """
            CREATE TABLE IF NOT EXISTS ncaam_net_rankings (
                team_name TEXT PRIMARY KEY,
                rank INTEGER,
                record TEXT,
                conf TEXT,
                road TEXT,
                neutral TEXT,
                home TEXT,
                quad1 TEXT,
                quad2 TEXT,
                quad3 TEXT,
                quad4 TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        for r in rows:
            if not r.school:
                continue
                
            _exec(conn, """
                INSERT INTO ncaam_net_rankings 
                (team_name, rank, record, conf, road, neutral, home, quad1, quad2, quad3, quad4)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (team_name) 
                DO UPDATE SET
                    rank = EXCLUDED.rank,
                    record = EXCLUDED.record,
                    conf = EXCLUDED.conf,
                    road = EXCLUDED.road,
                    neutral = EXCLUDED.neutral,
                    home = EXCLUDED.home,
                    quad1 = EXCLUDED.quad1,
                    quad2 = EXCLUDED.quad2,
                    quad3 = EXCLUDED.quad3,
                    quad4 = EXCLUDED.quad4,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                r.school.strip(), r.rank, r.record, r.conf, r.road, r.neutral, r.home,
                r.quad1, r.quad2, r.quad3, r.quad4
            ))
        
        conn.commit()
        print(f"[NCAAM NET] Saved {len(rows)} teams to database")

if __name__ == "__main__":
    ingest_ncaa_net()
