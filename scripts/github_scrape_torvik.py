#!/usr/bin/env python3
"""
GitHub Actions Torvik Scraper

Uses 2026_team_results.json endpoint (not blocked like schedule.php).
Persists to bt_team_metrics_daily table.
"""
import os
import sys
import json
import psycopg2
import psycopg2.extras
from datetime import datetime
from contextlib import contextmanager
import requests

DATABASE_URL = None

@contextmanager
def get_db_connection():
    """Get database connection."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
        yield conn
    finally:
        if conn:
            conn.close()


def _default_torvik_year() -> int:
    import os
    import sys
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from src.utils.ncaam_season import current_ncaam_season_end_year
    return current_ncaam_season_end_year()


def fetch_team_results(year: int = None):
    """
    Fetch from {year}_team_results.json (works without anti-bot block).
    """
    if year is None:
        year = _default_torvik_year()
    url = f"https://barttorvik.com/{year}_team_results.json"
    print(f"[FETCH] Getting {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[FETCH] Got {len(data)} teams")
            return data
    except Exception as e:
        print(f"[FETCH] Error: {e}")
    
    return None


def save_to_database(teams: list):
    """Insert/update team metrics in bt_team_metrics_daily."""
    if not teams:
        print("[DB] No data to save")
        return 0
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    query = """
    INSERT INTO bt_team_metrics_daily 
        (team_text, date, adj_off, adj_def, adj_tempo, luck, created_at)
    VALUES 
        (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (team_text, date) DO UPDATE SET
        adj_off = EXCLUDED.adj_off,
        adj_def = EXCLUDED.adj_def,
        adj_tempo = EXCLUDED.adj_tempo,
        luck = EXCLUDED.luck
    """
    
    count = 0
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        for row in teams:
            try:
                # Parse Torvik JSON structure
                # [rank, name, conf, record, adjOE, adjOE_rank, adjDE, adjDE_rank, ...]
                if not isinstance(row, list) or len(row) < 8:
                    continue
                
                name = row[1]
                adj_oe = float(row[4]) if row[4] else None
                adj_de = float(row[6]) if row[6] else None
                
                # Find tempo (usually around index 21-25, value between 55-85)
                tempo = None
                for idx in range(20, 26):
                    try:
                        val = float(row[idx])
                        if 55.0 < val < 85.0:
                            tempo = val
                            break
                    except:
                        continue
                
                # Luck is typically at index 33
                luck = None
                if len(row) > 33:
                    try:
                        luck = float(row[33])
                    except:
                        pass
                
                cur.execute(query, (
                    name,
                    today,
                    adj_oe,
                    adj_de,
                    tempo,
                    luck,
                    datetime.now()
                ))
                count += 1
                
            except Exception as e:
                print(f"[DB] Error saving row: {e}")
                continue
        
        conn.commit()
    
    return count


def main():
    global DATABASE_URL
    
    print("=" * 50)
    print("GitHub Actions Torvik Scraper")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 50)
    
    # Get DATABASE_URL
    DATABASE_URL = (
        os.environ.get('DATABASE_URL') or 
        os.environ.get('POSTGRES_URL') or 
        os.environ.get('DB_URL')
    )
    
    if not DATABASE_URL:
        print("[ERROR] No database URL found!")
        sys.exit(1)
    
    print("[OK] Database URL configured")
    
    # Fetch from team_results.json
    teams = fetch_team_results(year=_default_torvik_year())
    
    if not teams:
        print("[WARNING] Could not fetch team data")
        print("[INFO] Model will use cached data")
        sys.exit(0)  # Exit success
    
    # Save to database
    saved = save_to_database(teams)
    print(f"[DB] Saved {saved} team records")
    
    print("\n" + "=" * 50)
    print("✅ Complete!")
    sys.exit(0)


if __name__ == "__main__":
    main()
