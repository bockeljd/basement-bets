
import sys
import os
from datetime import datetime
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_db_connection, _exec

def check_dates():
    print(f"Server Time: {datetime.now()}")
    query = """
    SELECT DATE(start_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') as game_date, COUNT(*) 
    FROM events 
    GROUP BY game_date 
    ORDER BY game_date DESC;
    """
    with get_db_connection() as conn:
        rows = _exec(conn, query).fetchall()
        if not rows:
            print("No events found in DB.")
        else:
            for r in rows:
                print(f"Date: {r['game_date']} | Count: {r['count']}")

if __name__ == "__main__":
    check_dates()
