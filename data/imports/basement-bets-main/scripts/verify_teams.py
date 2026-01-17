import sys
import os
import sqlite3
import psycopg2
from psycopg2.extras import DictCursor

# Ensure root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec

def verify_teams():
    print("--- Team Identity Verification ---")
    with get_db_connection() as conn:
        # 1. Count Teams by League
        print("\n[Canonical Teams Count]")
        rows = _exec(conn, "SELECT league, COUNT(*) FROM teams GROUP BY league").fetchall()
        for r in rows:
            print(f"  {r[0]}: {r[1]}")
            
        # 2. Count Maps by Provider/League
        print("\n[Provider Maps Count]")
        rows = _exec(conn, "SELECT provider, league, COUNT(*) FROM team_provider_map GROUP BY provider, league").fetchall()
        for r in rows:
            print(f"  {r[0]} ({r[1]}): {r[2]}")
            
        # 3. EPL Check
        print("\n[EPL Check]")
        epl_count = _exec(conn, "SELECT COUNT(*) FROM teams WHERE league='EPL'").fetchone()[0]
        print(f"  Total EPL Teams: {epl_count} (Expected ~20)")
        
        # 4. NFL Check
        print("\n[NFL Check]")
        nfl_count = _exec(conn, "SELECT COUNT(*) FROM teams WHERE league='NFL'").fetchone()[0]
        print(f"  Total NFL Teams: {nfl_count} (Expected ~32)")
        
        # 5. NCAAM Check
        print("\n[NCAAM Check]")
        ncaam_count = _exec(conn, "SELECT COUNT(*) FROM teams WHERE league='NCAAM'").fetchone()[0]
        print(f"  Total NCAAM Teams: {ncaam_count} (Expected > 300)")

        # 6. Events Check
        print("\n[Events v2 Check]")
        events_count = _exec(conn, "SELECT COUNT(*) FROM events_v2").fetchone()[0]
        print(f"  Total Canonical Events: {events_count}")
        
        # 7. Coverage Check
        print("\n[Event Coverage]")
        prov_map = _exec(conn, "SELECT COUNT(*) FROM event_providers").fetchone()[0]
        print(f"  Provider Links: {prov_map} (Should match Events roughly)")

if __name__ == "__main__":
    verify_teams()
