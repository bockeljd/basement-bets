#!/usr/bin/env python3
"""
GitHub Actions Torvik Scraper

Uses 2026_team_results.json endpoint (not blocked like schedule.php).
Persists to bt_team_metrics_daily table.
"""
import os
import sys
import csv
import io
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
        (team_text, date, adj_off, adj_def, adj_tempo, luck, continuity, torvik_rank, record, created_at)
    VALUES 
        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (team_text, date) DO UPDATE SET
        adj_off = EXCLUDED.adj_off,
        adj_def = EXCLUDED.adj_def,
        adj_tempo = EXCLUDED.adj_tempo,
        luck = COALESCE(EXCLUDED.luck, bt_team_metrics_daily.luck),
        continuity = COALESCE(EXCLUDED.continuity, bt_team_metrics_daily.continuity),
        torvik_rank = COALESCE(EXCLUDED.torvik_rank, bt_team_metrics_daily.torvik_rank),
        record = COALESCE(EXCLUDED.record, bt_team_metrics_daily.record)
    """
    
    count = 0
    with get_db_connection() as conn:
        cur = conn.cursor()
        for ddl in (
            "ALTER TABLE bt_team_metrics_daily ADD COLUMN IF NOT EXISTS luck REAL;",
            "ALTER TABLE bt_team_metrics_daily ADD COLUMN IF NOT EXISTS continuity REAL;",
            "ALTER TABLE bt_team_metrics_daily ADD COLUMN IF NOT EXISTS torvik_rank INTEGER;",
            "ALTER TABLE bt_team_metrics_daily ADD COLUMN IF NOT EXISTS record TEXT;",
        ):
            try:
                cur.execute(ddl)
            except Exception:
                conn.rollback()
        conn.commit()
        
        for row in teams:
            try:
                # Parse Torvik JSON structure
                # [rank, name, conf, record, adjOE, adjOE_rank, adjDE, adjDE_rank, ...]
                if not isinstance(row, list) or len(row) < 8:
                    continue
                
                torvik_rank = None
                try:
                    torvik_rank = int(row[0]) if row[0] is not None else None
                except Exception:
                    pass
                name = row[1]
                record = str(row[3]) if len(row) > 3 and row[3] is not None else None
                adj_oe = float(row[4]) if row[4] else None
                adj_de = float(row[6]) if row[6] else None
                
                # Find tempo (live BartTorvik places AdjTempo at [44], then fallback slots)
                tempo = None
                for idx in (44, 21, 22, 45, 42, 20, 23, 24, 25):
                    try:
                        if len(row) > idx and row[idx] is not None:
                            val = float(row[idx])
                            if 55.0 < val < 85.0:
                                tempo = val
                                break
                    except Exception:
                        continue
                
                # Luck is typically at index 33
                luck = None
                if len(row) > 33 and row[33] is not None:
                    try:
                        l_val = float(row[33])
                        if abs(l_val) <= 1.0:
                            luck = l_val
                    except Exception:
                        pass

                # BartTorvik team_results.json places AdjTempo at [44] and does not publish roster continuity
                continuity = None
                
                cur.execute(query, (
                    name,
                    today,
                    adj_oe,
                    adj_de,
                    tempo,
                    luck,
                    continuity,
                    torvik_rank,
                    record,
                    datetime.now()
                ))
                count += 1
                
            except Exception as e:
                print(f"[DB] Error saving row: {e}")
                continue
        
        conn.commit()
    
    return count


def fetch_player_stats(year: int = None):
    """
    Fetch full D1 rotation player stats from BartTorvik getadvstats.php CSV.
    """
    if year is None:
        year = _default_torvik_year()
    url = f"https://barttorvik.com/getadvstats.php?year={year}&csv=1"
    print(f"[FETCH] Getting player rotation stats from {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200 or not resp.text:
            print(f"[FETCH] Player CSV returned status {resp.status_code}")
            return []
        rows = list(csv.reader(io.StringIO(resp.text)))
        parsed = []
        for row in rows:
            if len(row) < 7:
                continue
            player_name = str(row[0] or "").strip()
            team_text = str(row[1] or "").strip()
            if not player_name or not team_text or player_name.lower() == "player_name":
                continue
            try:
                gp = int(float(row[3])) if row[3] else 0
            except Exception:
                gp = 0
            try:
                min_pct = float(row[4]) if row[4] else 0.0
            except Exception:
                min_pct = 0.0
            if gp < 1 or min_pct < 12.0:
                continue
            def _f(idx):
                try:
                    return float(row[idx]) if len(row) > idx and row[idx] != "" else None
                except Exception:
                    return None
            parsed.append({
                "player_name": player_name,
                "team_text": team_text,
                "gp": gp,
                "min_pct": round(min_pct, 1),
                "ortg": _f(5),
                "usg": _f(6),
                "porpag": _f(28),
                "bpm": _f(50),
            })
        print(f"[FETCH] Parsed {len(parsed)} rotation players (min% >= 12.0)")
        return parsed
    except Exception as e:
        print(f"[FETCH] Player stats error: {e}")
        return []


def save_player_stats_to_database(players: list):
    """Batch upsert D1 rotation player stats into bt_player_stats_daily."""
    if not players:
        print("[DB] No player stats to save")
        return 0

    today = datetime.now().strftime('%Y-%m-%d')
    now_ts = datetime.now()

    # Deduplicate by (team_text, player_name) keeping highest min_pct
    dedup = {}
    for p in players:
        key = (p["team_text"], p["player_name"])
        if key not in dedup or p["min_pct"] > dedup[key]["min_pct"]:
            dedup[key] = p
    values = [
        (
            today,
            p["team_text"],
            p["player_name"],
            p["gp"],
            p["min_pct"],
            p["ortg"],
            p["usg"],
            p["porpag"],
            p["bpm"],
            now_ts,
        )
        for p in dedup.values()
    ]

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bt_player_stats_daily (
                asof_date DATE NOT NULL,
                team_text TEXT NOT NULL,
                player_name TEXT NOT NULL,
                gp INTEGER,
                min_pct REAL,
                ortg REAL,
                usg REAL,
                porpag REAL,
                bpm REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (asof_date, team_text, player_name)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_bt_player_stats_team_date
            ON bt_player_stats_daily (team_text, asof_date DESC);
        """)
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO bt_player_stats_daily
                (asof_date, team_text, player_name, gp, min_pct, ortg, usg, porpag, bpm, updated_at)
            VALUES %s
            ON CONFLICT (asof_date, team_text, player_name) DO UPDATE SET
                gp = EXCLUDED.gp,
                min_pct = EXCLUDED.min_pct,
                ortg = EXCLUDED.ortg,
                usg = EXCLUDED.usg,
                porpag = EXCLUDED.porpag,
                bpm = EXCLUDED.bpm,
                updated_at = EXCLUDED.updated_at
            """,
            values,
            page_size=500,
        )
        conn.commit()
    return len(values)


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
    
    year = _default_torvik_year()
    # Fetch from team_results.json
    teams = fetch_team_results(year=year)
    
    if not teams:
        print("[WARNING] Could not fetch team data")
        print("[INFO] Model will use cached data")
    else:
        # Save to database
        saved = save_to_database(teams)
        print(f"[DB] Saved {saved} team records")

    # Fetch and save full D1 rotation player stats
    players = fetch_player_stats(year=year)
    if players:
        saved_p = save_player_stats_to_database(players)
        print(f"[DB] Saved {saved_p} rotation player records")
    
    print("\n" + "=" * 50)
    print("✅ Complete!")
    sys.exit(0)


if __name__ == "__main__":
    main()
