
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_db_connection, _exec

def check_todays_odds():
    date_str = "2026-01-23" # Today based on server time
    print(f"Checking odds for {date_str}...")
    
    query = """
    SELECT e.id, e.home_team, e.away_team, count(s.id) as odds_count
    FROM events e
    LEFT JOIN odds_snapshots s ON e.id = s.event_id
    WHERE DATE(e.start_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = :date
    GROUP BY e.id, e.home_team, e.away_team
    ORDER BY odds_count DESC
    LIMIT 10;
    """
    
    with get_db_connection() as conn:
        rows = _exec(conn, query, {"date": date_str}).fetchall()
        if not rows:
            print("No events found for today.")
        else:
            for r in rows:
                print(f"{r['home_team']} vs {r['away_team']} | Odds Count: {r['odds_count']}")

if __name__ == "__main__":
    check_todays_odds()
