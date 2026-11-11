
import os
import sys
import pandas as pd
sys.path.append(os.getcwd())
from src.database import get_db_connection

def debug_query():
    # Copy of the query from engine, but selecting * from CTE and NO filtering
    query = """
        WITH game_metrics AS (
            SELECT 
                e.id,
                e.start_time,
                e.home_team,
                e.away_team,
                gr.home_score,
                gr.away_score,
                (
                    SELECT line_value 
                    FROM odds_snapshots os 
                    WHERE os.event_id = e.id 
                      AND os.market_type = 'spread' 
                      AND os.captured_at <= (e.start_time AT TIME ZONE 'UTC')
                    ORDER BY os.captured_at DESC LIMIT 1
                ) as close_spread,
                (
                    SELECT line_value 
                    FROM odds_snapshots os 
                    WHERE os.event_id = e.id 
                      AND os.market_type = 'total' 
                      AND os.captured_at <= (e.start_time AT TIME ZONE 'UTC')
                    ORDER BY os.captured_at DESC LIMIT 1
                ) as close_total,
                mh.adj_tempo as home_pace,
                mh.team_text as home_metrics_name,
                ma.team_text as away_metrics_name
            FROM events e
            JOIN game_results gr ON e.id = gr.event_id
            LEFT JOIN (
                SELECT team_text, adj_tempo, adj_off, adj_def
                FROM bt_team_metrics_daily
                WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
            ) mh ON LOWER(e.home_team) LIKE '%%' || LOWER(mh.team_text) || '%%'
            LEFT JOIN (
                SELECT team_text, adj_tempo, adj_off, adj_def
                FROM bt_team_metrics_daily
                WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
            ) ma ON LOWER(e.away_team) LIKE '%%' || LOWER(ma.team_text) || '%%'
            WHERE e.start_time >= %(start)s 
              AND e.start_time < %(end)s
              AND (e.league = 'NCAAM' OR e.league = 'ncaab')
              AND gr.final = TRUE
        )
        SELECT * FROM game_metrics
        LIMIT 10
    """
    
    from src.utils.ncaam_season import ncaam_season_date_bounds
    season_start, season_end = ncaam_season_date_bounds()
    print(f"Running Debug Query ({season_start} to {season_end})...")
    with get_db_connection() as conn:
        df = pd.read_sql_query(query, conn, params={"start": season_start, "end": season_end})
        
    if df.empty:
        print("DF is EMPTY! Events/Results Join failing?")
    else:
        print("First 5 rows:")
        print(df.to_string())

if __name__ == "__main__":
    debug_query()
