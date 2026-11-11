
import os
import sys
sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec
from src.utils.ncaam_season import (
    current_ncaam_season_long,
    ncaam_season_compact_bounds,
    ncaam_season_date_bounds,
)

def check_data():
    season_start, _ = ncaam_season_date_bounds()
    season_start_compact, _ = ncaam_season_compact_bounds()
    season_long = current_ncaam_season_long()
    with get_db_connection() as conn:
        print("--- League Distribution ---")
        leagues = _exec(conn, "SELECT league, COUNT(*) FROM events GROUP BY league").fetchall()
        for l in leagues:
            print(f"{l[0]}: {l[1]}")
            
        print(f"\n--- {season_long} NCAAM Check ---")
        # Broad filter
        query_games = """
        SELECT COUNT(*) 
        FROM events e
        JOIN game_results r ON e.id = r.event_id
        WHERE e.start_time >= %s
          AND (e.league ILIKE '%%ncaa%%' OR e.league ILIKE '%%college%%')
          AND r.final = TRUE
        """
        games_count = _exec(conn, query_games, (season_start,)).fetchone()[0]
        print(f"Completed Games (Broad Filter): {games_count}")

        # Odds
        query_odds = """
        SELECT COUNT(DISTINCT e.id)
        FROM events e
        JOIN odds_snapshots os ON e.id = os.event_id
        WHERE e.start_time >= %s
          AND (e.league ILIKE '%%ncaa%%' OR e.league ILIKE '%%college%%')
        """
        odds_count = _exec(conn, query_odds, (season_start,)).fetchone()[0]
        print(f"Games with Odds: {odds_count}")
        
        # Metrics
        ct = _exec(conn, "SELECT COUNT(*) FROM bt_team_metrics_daily WHERE date >= %s", (season_start_compact,)).fetchone()[0]
        print(f"Team Metrics Rows (since Nov 1): {ct}")

if __name__ == "__main__":
    check_data()
