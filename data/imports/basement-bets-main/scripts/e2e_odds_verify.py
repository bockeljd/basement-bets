
import os
import sys
from datetime import datetime
import pandas as pd
from src.database import get_db_connection, _exec
from src.services.odds_adapter import OddsAdapter

def run_e2e():
    print("1. Clearing odds_snapshots and CSV cache...")
    with get_db_connection() as conn:
        _exec(conn, "DELETE FROM odds_snapshots")
        conn.commit()
    
    # Clear NCAAB CSV cache to force ingestion
    csv_path = "/Users/jordanbockelman/Basement Bets/bet_tracker/data/bets_db/ncaab_bets_db.csv"
    if os.path.exists(csv_path):
        os.remove(csv_path)
        print(f"Removed cache: {csv_path}")
    
    print("2. Running Ingestion (pull_odds.py logic) for NCAAM...")
    import scripts.pull_odds as puller
    # Targeting a date with known events in events_v2 for join verification
    target_date = "20260112"
    puller.process_sport('ncaab', [target_date])
    
    print("\n3. Verifying Results...")
    with get_db_connection() as conn:
        print("\n--- Market Coverage (Canonical Joins) ---")
        sql3 = """
        SELECT e.league,
               o.market_type,
               COUNT(*) AS rows,
               COUNT(DISTINCT o.event_id) AS events_covered
        FROM odds_snapshots o
        JOIN events_v2 e ON e.id = o.event_id
        GROUP BY 1,2
        ORDER BY 1,2;
        """
        try:
            df3 = pd.read_sql(sql3, conn)
            if df3.empty:
                print("No overlapping events found in events_v2 for the current ingestion.")
                # Show generic counts
                rows = _exec(conn, "SELECT COUNT(*) FROM odds_snapshots").fetchone()[0]
                print(f"Total rows in odds_snapshots: {rows}")
                if rows > 0:
                    print("Sample event_ids in snapshots (first 5):")
                    cur = conn.cursor()
                    cur.execute("SELECT event_id FROM odds_snapshots LIMIT 5")
                    for r in cur.fetchall(): print(f" - {r[0]}")
            else:
                print(df3.to_string(index=False))
        except Exception as e:
            print(f"Error Query 3: {e}")

        print("\n--- Uniqueness Check (Idempotency) ---")
        sql5 = """
        SELECT event_id, market_type, side, line, book, captured_bucket, COUNT(*) AS n
        FROM odds_snapshots
        GROUP BY 1,2,3,4,5,6
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        LIMIT 50;
        """
        try:
            df5 = pd.read_sql(sql5, conn)
            if df5.empty:
                print("No duplicates found. SUCCESS.")
            else:
                print("DUPLICATES FOUND:")
                print(df5.to_string(index=False))
        except Exception as e:
            print(f"Error Query 5: {e}")

if __name__ == "__main__":
    run_e2e()
