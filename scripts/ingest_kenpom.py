#!/usr/bin/env python3
"""
Ingest KenPom Data into Database

Scrapes KenPom.com and saves efficiency ratings to database
"""

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.kenpom_scraper import KenPomScraper
from src.database import get_db_connection, _exec

def ingest_kenpom():
    """Scrape and ingest KenPom data"""
    
    scraper = KenPomScraper()
    
    # Scrape homepage
    teams = scraper.scrape_homepage_rankings()
    
    if not teams:
        print("[ERROR] No teams scraped from KenPom")
        return
    
    print(f"[KENPOM] Scraped {len(teams)} teams")
    
    # Create table
    with get_db_connection() as conn:
        _exec(conn, """
            CREATE TABLE IF NOT EXISTS kenpom_ratings (
                team_name TEXT PRIMARY KEY,
                rank INTEGER,
                conference TEXT,
                record TEXT,
                adj_em REAL,
                adj_o REAL,
                adj_d REAL,
                adj_t REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert/update teams
        for team in teams:
            _exec(conn, """
                INSERT INTO kenpom_ratings 
                (team_name, rank, conference, record, adj_em, adj_o, adj_d, adj_t)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (team_name) 
                DO UPDATE SET
                    rank = EXCLUDED.rank,
                    conference = EXCLUDED.conference,
                    record = EXCLUDED.record,
                    adj_em = EXCLUDED.adj_em,
                    adj_o = EXCLUDED.adj_o,
                    adj_d = EXCLUDED.adj_d,
                    adj_t = EXCLUDED.adj_t,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                team['team'],
                team['rank'],
                team['conference'],
                team['record'],
                team['adj_em'],
                team['adj_o'],
                team['adj_d'],
                team['adj_t']
            ))
        
        conn.commit()
        print(f"[KENPOM] Saved {len(teams)} teams to database")
    
    # Show top 10
    print("\nTop 10 Teams:")
    for team in teams[:10]:
        print(f"  {team['rank']:2d}. {team['team']:25s} AdjEM: {team['adj_em']:6.2f}")

if __name__ == "__main__":
    ingest_kenpom()
