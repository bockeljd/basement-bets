import sqlite3
import os
import psycopg2
import psycopg2.pool
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import urlparse

from src.config import settings

# Detect Vercel Environment
# IS_VERCEL is still useful for some runtime distinctions, but we prefer APP_ENV
IS_VERCEL = os.environ.get("VERCEL") == "1"

# Default to SQLite if no DATABASE_URL is set
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'bets.db')

# Global Postgres Connection Pool
pg_pool = None

def get_db_type():
    if settings.DATABASE_URL:
        return 'postgres'
    return 'sqlite'

@contextmanager
def get_db_connection():
    global pg_pool
    if settings.DATABASE_URL:
        # PRODUCTION/PREVIEW/STAGING: Use Postgres with Pooling
        if pg_pool is None:
            try:
                # Initialize pool (Min 1, Max 20)
                # ThreadedConnectionPool is safer for FastAPI scenarios
                pg_pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 20, 
                    dsn=settings.DATABASE_URL, 
                    cursor_factory=psycopg2.extras.DictCursor
                )
                print("[DB] Initialized Postgres Connection Pool")
            except Exception as e:
                print(f"[DB] Pool init failed: {e}")
                raise e

        conn = pg_pool.getconn()
        try:
            yield conn
        finally:
            pg_pool.putconn(conn)
    else:
        # LOCAL SQLITE
        # print(f"[DEBUG] Connecting to SQLite: {DB_PATH}")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

def _exec(conn, sql, params=None):
    """Unified execute helper."""
    if params is None: 
        params = ()
    
    # Simple detection based on connection type
    is_pg = hasattr(conn, 'cursor_factory')
    
    if is_pg:
        # Postgres Syntax Adaptation
        # 1. Convert ? to %s
        sql = sql.replace('?', '%s')
        
        # 2. Convert :key to %(key)s, avoiding :: cast operations
        # Look for :key where it is NOT preceded by :
        if ':' in sql and not '%(' in sql:
            import re
            # Only match :identifier where identifier starts with a letter or underscore
            sql = re.sub(r'(?<!:):([a-zA-Z_]\w*)', r'%(\1)s', sql)
            
        # 3. Handle INSERT OR IGNORE
        if "INSERT OR IGNORE" in sql:
            sql = sql.replace("INSERT OR IGNORE", "INSERT")
            sql += " ON CONFLICT DO NOTHING"
            
    cursor = conn.cursor()
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    return cursor

def init_db():
    db_type = get_db_type()
    
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            account_id TEXT,
            provider TEXT NOT NULL,
            date TEXT NOT NULL, 
            sport TEXT NOT NULL,
            bet_type TEXT NOT NULL,
            wager REAL NOT NULL,
            profit REAL NOT NULL,
            status TEXT NOT NULL,
            description TEXT NOT NULL,
            selection TEXT,
            odds INTEGER,
            closing_odds INTEGER,
            is_live BOOLEAN DEFAULT FALSE,
            is_bonus BOOLEAN DEFAULT FALSE,
            is_parlay BOOLEAN DEFAULT FALSE,
            hash_id TEXT, -- For Idempotency (Phase 1)
            raw_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            -- UNIQUE(user_id, provider, description, date, wager) -- Replaced by hash_id check? Or keep as backup.
            UNIQUE(user_id, provider, description, date, wager)
        );
        """
    else:
        # Postgres Schema
        schema = """
        CREATE TABLE IF NOT EXISTS bets (
            id SERIAL PRIMARY KEY,
            user_id UUID NOT NULL,
            account_id UUID,
            provider TEXT NOT NULL,
            date TEXT NOT NULL, 
            sport TEXT NOT NULL,
            bet_type TEXT NOT NULL,
            wager REAL NOT NULL,
            profit REAL NOT NULL,
            status TEXT NOT NULL,
            description TEXT NOT NULL,
            selection TEXT,
            odds INTEGER,
            closing_odds INTEGER,
            is_live BOOLEAN DEFAULT FALSE,
            is_bonus BOOLEAN DEFAULT FALSE,
            raw_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, provider, description, date, wager)
        );
        """

    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print(f"Database ({db_type}) bets table initialized.")

    # Initialize other tables
    init_transactions_tab()
    init_events_db()
    init_game_results_db()
    init_model_history()
    init_odds_snapshots_db()
    init_linking_queue_db()
    init_settlement_db()
    init_model_health_db()
    init_model_health_insights_db()
    init_policy_db()
    init_ingestion_runs_db()
    init_smart_curation_db()
    init_bt_team_metrics_db()
    init_enrichment_db()

def init_bt_team_metrics_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS bt_team_metrics_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_text TEXT NOT NULL,
            date TEXT NOT NULL,
            adj_off REAL,
            adj_def REAL,
            adj_tempo REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_text, date)
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS bt_team_metrics_daily (
            id SERIAL PRIMARY KEY,
            team_text TEXT NOT NULL,
            date TEXT NOT NULL,
            adj_off REAL,
            adj_def REAL,
            adj_tempo REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_text, date)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()

def init_enrichment_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS action_game_enrichment (
            id TEXT PRIMARY KEY, -- UUID
            event_id TEXT NOT NULL, -- FK to events_v2
            provider TEXT DEFAULT 'ACTION_NETWORK',
            provider_game_id TEXT,
            as_of_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            payload_json TEXT,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_injuries (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            team_id TEXT, -- Nullable FK
            player_name TEXT NOT NULL,
            player_id TEXT,
            status TEXT, -- OUT/QUESTIONABLE
            description TEXT,
            reported_at TIMESTAMP,
            source_url TEXT,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_splits (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            market_type TEXT, -- SPREAD/TOTAL/ML
            selection TEXT, -- HOME/AWAY/OVER
            line REAL,
            bet_pct REAL,
            handle_pct REAL,
            sharp_indicator TEXT,
            as_of_ts TIMESTAMP,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_props (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            prop_type TEXT, -- PLAYER_POINTS
            player_name TEXT,
            player_id TEXT,
            side TEXT, -- OVER/UNDER
            line REAL,
            price INTEGER,
            book TEXT,
            as_of_ts TIMESTAMP,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_news (
            id TEXT PRIMARY KEY,
            league TEXT,
            team_id TEXT,
            event_id TEXT,
            headline TEXT,
            summary TEXT,
            url TEXT,
            published_at TIMESTAMP,
            source TEXT DEFAULT 'ACTION_NETWORK',
            fingerprint TEXT UNIQUE
        );
        -- Indexes for SQLite
        CREATE INDEX IF NOT EXISTS idx_enrich_event ON action_game_enrichment(event_id);
        CREATE INDEX IF NOT EXISTS idx_splits_event ON action_splits(event_id);
        CREATE INDEX IF NOT EXISTS idx_props_player ON action_props(player_name);
        """
    else:
        # Postgres
        schema = """
        CREATE TABLE IF NOT EXISTS action_game_enrichment (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id UUID NOT NULL,
            provider TEXT DEFAULT 'ACTION_NETWORK',
            provider_game_id TEXT,
            as_of_ts TIMESTAMPTZ DEFAULT NOW(),
            payload_json JSONB,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_injuries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id UUID NOT NULL,
            team_id UUID,
            player_name TEXT NOT NULL,
            player_id TEXT,
            status TEXT,
            description TEXT,
            reported_at TIMESTAMPTZ,
            source_url TEXT,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_splits (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id UUID NOT NULL,
            market_type TEXT, 
            selection TEXT,
            line REAL,
            bet_pct REAL,
            handle_pct REAL,
            sharp_indicator TEXT,
            as_of_ts TIMESTAMPTZ,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_props (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id UUID NOT NULL,
            prop_type TEXT,
            player_name TEXT,
            player_id TEXT,
            side TEXT,
            line REAL,
            price INTEGER,
            book TEXT,
            as_of_ts TIMESTAMPTZ,
            fingerprint TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS action_news (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            league TEXT,
            team_id UUID,
            event_id UUID,
            headline TEXT,
            summary TEXT,
            url TEXT,
            published_at TIMESTAMPTZ,
            source TEXT DEFAULT 'ACTION_NETWORK',
            fingerprint TEXT UNIQUE
        );
        -- Indexes for Postgres
        CREATE INDEX IF NOT EXISTS idx_enrich_event ON action_game_enrichment(event_id);
        CREATE INDEX IF NOT EXISTS idx_splits_event ON action_splits(event_id);
        CREATE INDEX IF NOT EXISTS idx_props_player ON action_props(player_name);
        """

    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Action Network Enrichment tables initialized.")

# --- Curation / Policy Helpers ---

def aggregate_daily_performance(target_date: str):
    """
    Calculates aggregate stats (ROI, CLV, Hit Rate) for a given date
    from the 'bets' table and populates 'market_performance_daily'.
    """
    print(f"Aggregating performance for {target_date}...")
    
    # 1. Clear existing entry for this date (Idempotency)
    with get_db_connection() as conn:
        _exec(conn, "DELETE FROM market_performance_daily WHERE date = :date", {"date": target_date})
        conn.commit()

    # 2. Aggregate from Bets (Real Skin in the Game)
    # Group by sport (League) and bet_type (Market Type)
    query = """
    SELECT 
        sport as league,
        bet_type as market_type,
        SUM(wager) as total_wager,
        SUM(profit) as total_profit,
        COUNT(*) as sample_size,
        SUM(CASE WHEN status = 'Won' THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN status = 'Lost' THEN 1 ELSE 0 END) as losses,
        SUM(CASE WHEN status = 'Push' THEN 1 ELSE 0 END) as pushes,
        -- Approximate CLV: (Closing Prob - Bet Prob)
        -- We'd need to convert odds to prob. For now, placeholder or use 0.
        0.0 as avg_clv 
    FROM bets
    WHERE date = :date
    AND status IN ('Won', 'Lost', 'Push')
    GROUP BY sport, bet_type
    """
    
    with get_db_connection() as conn:
        rows = _exec(conn, query, {"date": target_date}).fetchall()
        
        for row in rows:
            league = row['league']
            mkt = row['market_type']
            vol = row['total_wager']
            profit = row['total_profit']
            n = row['sample_size']
            
            roi = profit / vol if vol > 0 else 0.0
            # Hit Rate (ignoring pushes for den? or including?)
            # Standard: Wins / (Wins + Losses)
            decisive = row['wins'] + row['losses']
            hit_rate = row['wins'] / decisive if decisive > 0 else 0.0
            clv = 0.0 # TODO: Implement Odds->Prob conversion for CLV
            
            # Insert
            ins_q = """
            INSERT INTO market_performance_daily 
            (date, league, market_type, roi, clv, hit_rate, sample_size)
            VALUES (:date, :league, :mkt, :roi, :clv, :hr, :n)
            """
            _exec(conn, ins_q, {
                "date": target_date,
                "league": league,
                "mkt": mkt,
                "roi": roi,
                "clv": clv,
                "hr": hit_rate,
                "n": n
            })
        conn.commit()
    print(f"Aggregation complete for {target_date}.")

def get_market_performance_window(league: str, market_type: str, days: int = 30) -> dict:
    """
    Fetch rolling performance stats.
    """
    query = """
    SELECT 
        SUM(roi * sample_size) / SUM(sample_size) as weighted_roi, -- approx
        AVG(clv) as avg_clv,
        SUM(sample_size) as total_n
    FROM market_performance_daily
    WHERE league = :league AND market_type = :mkt
    AND date >= date('now', :modifier)
    """
    # SQLite modifier format: '-30 days'
    mod = f"-{days} days"
    
    # Postgres uses interval.
    # We used date('now', ...) which is SQLite. 
    # For compatibility we might need separate logic, but let's stick to existing pattern or generic SQL.
    # Generic: date >= CURRENT_DATE - INTERVAL '30 days' (PG) vs date('now', '-30 days') (SQLite).
    
    # Let's use Python date math to be safe across DBs.
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    q_safe = """
    SELECT 
        SUM(profit) as total_profit,
        SUM(wager) as total_wager,
        AVG(clv) as avg_clv, -- average of daily averages (imperfect but okay)
        SUM(sample_size) as total_n
    FROM market_performance_daily
    WHERE league = :league AND market_type = :mkt
    AND date >= :cutoff
    """
    # Wait, market_performance_daily has ROI, not profit/wager? 
    # I didn't store profit/wager in market_performance_daily above. 
    # I stored ROI. 
    # To aggregate ROIs efficiently, I need weighted avg.
    # sum(roi * n) / sum(n).
    
    q_weighted = """
    SELECT 
        SUM(roi * sample_size) as total_roi_weight, 
        SUM(sample_size) as total_n,
        AVG(clv) as avg_clv
    FROM market_performance_daily
    WHERE league = :league AND market_type = :mkt
    AND date >= :cutoff
    """
    
    with get_db_connection() as conn:
        row = _exec(conn, q_weighted, {"league": league, "mkt": market_type, "cutoff": cutoff}).fetchone()
        if row and row['total_n'] and row['total_n'] > 0:
            return {
                "roi": row['total_roi_weight'] / row['total_n'],
                "clv": row['avg_clv'],
                "sample_size": row['total_n']
            }
        return None

def get_market_allowlist() -> dict:
    """
    Returns dict: {(league, market_type): status}
    """
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT league, market_type, status FROM market_allowlist").fetchall()
        return {(r['league'], r['market_type']): r['status'] for r in rows}

def update_market_status(league: str, market_type: str, status: str, reason: str):
    """
    Update Allowlist Status.
    """
    print(f"[DB] Updating {league}/{market_type} -> {status} ({reason})")
    q = """
    INSERT INTO market_allowlist (league, market_type, status, reason, updated_at)
    VALUES (:l, :m, :s, :r, CURRENT_TIMESTAMP)
    ON CONFLICT(league, market_type) DO UPDATE SET
        status = excluded.status,
        reason = excluded.reason,
        updated_at = CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        _exec(conn, q, {"l": league, "m": market_type, "s": status, "r": reason})
        conn.commit()

# --- End Curation Helpers ---

def get_team_efficiency_by_name(team_name: str, date: str = None) -> dict:
    """
    Fetch raw efficiency metrics for a team by name.
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
        
    query = """
    SELECT * FROM bt_team_metrics_daily 
    WHERE team_text = :team_text AND date = :date
    """
    with get_db_connection() as conn:
        cursor = _exec(conn, query, {"team_text": team_name, "date": date})
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None

def init_smart_curation_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS model_registry (
            version TEXT PRIMARY KEY, -- e.g. "ncaam_v1_2024"
            status TEXT DEFAULT 'CANDIDATE', -- PRIMARY, SHADOW, DISABLED
            w_spread REAL,
            w_total REAL,
            sigma_margin_base REAL,
            sigma_total_base REAL,
            signal_caps_json TEXT, -- JSON
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT
        );
        CREATE TABLE IF NOT EXISTS market_allowlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT NOT NULL,
            market_type TEXT NOT NULL, -- SPREAD, TOTAL, etc.
            status TEXT DEFAULT 'SHADOW', -- ENABLED, DISABLED
            min_edge REAL,
            min_confidence REAL,
            max_units_per_day REAL,
            max_units_per_game REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT,
            UNIQUE(league, market_type)
        );
        CREATE TABLE IF NOT EXISTS market_performance_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            league TEXT NOT NULL,
            market_type TEXT NOT NULL,
            model_version TEXT NOT NULL,
            roi REAL,
            clv REAL,
            hit_rate REAL,
            brier_score REAL,
            sample_size INTEGER,
            data_quality_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, league, market_type, model_version)
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS model_registry (
            version TEXT PRIMARY KEY,
            status TEXT DEFAULT 'CANDIDATE',
            w_spread REAL,
            w_total REAL,
            sigma_margin_base REAL,
            sigma_total_base REAL,
            signal_caps_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT
        );
        CREATE TABLE IF NOT EXISTS market_allowlist (
            id SERIAL PRIMARY KEY,
            league TEXT NOT NULL,
            market_type TEXT NOT NULL,
            status TEXT DEFAULT 'SHADOW',
            min_edge REAL,
            min_confidence REAL,
            max_units_per_day REAL,
            max_units_per_game REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT,
            UNIQUE(league, market_type)
        );
        CREATE TABLE IF NOT EXISTS market_performance_daily (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            league TEXT NOT NULL,
            market_type TEXT NOT NULL,
            model_version TEXT NOT NULL,
            roi REAL,
            clv REAL,
            hit_rate REAL,
            brier_score REAL,
            sample_size INTEGER,
            data_quality_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, league, market_type, model_version)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Smart Curation (Registry/Allowlist) tables initialized.")

def add_closing_odds_column():
    pass # Deprecated / Managed by schema defaults now

def update_closing_odds(bet_id: int, closing_odds: int):
    query = "UPDATE bets SET closing_odds = ? WHERE id = ?"
    with get_db_connection() as conn:
        _exec(conn, query, (closing_odds, bet_id))
        conn.commit()

def init_model_history():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS model_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            sport TEXT NOT NULL,
            date TEXT,
            matchup TEXT NOT NULL,
            bet_on TEXT NOT NULL,
            market TEXT NOT NULL,
            market_line REAL,
            fair_line REAL,
            edge REAL,
            is_actionable BOOLEAN,
            result TEXT DEFAULT 'Pending',
            home_score REAL,
            away_score REAL,
            home_team TEXT,
            away_team TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(game_id, bet_on)
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS model_predictions (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            sport TEXT NOT NULL,
            date TEXT,
            matchup TEXT NOT NULL,
            bet_on TEXT NOT NULL,
            market TEXT NOT NULL,
            market_line REAL,
            fair_line REAL,
            edge REAL,
            is_actionable BOOLEAN,
            result TEXT DEFAULT 'Pending',
            home_score REAL,
            away_score REAL,
            home_team TEXT,
            away_team TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(game_id, bet_on)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Model predictions table initialized.")

def insert_model_prediction(pred: dict):
    query = """
    INSERT INTO model_predictions 
    (game_id, sport, date, matchup, bet_on, market, market_line, fair_line, edge, is_actionable, home_team, away_team)
    VALUES (:game_id, :sport, :start_time, :game, :bet_on, :market, :market_line, :fair_line, :edge, :is_actionable, :home_team, :away_team)
    ON CONFLICT (game_id, bet_on) DO NOTHING
    """
    with get_db_connection() as conn:
        _exec(conn, query, pred)
        conn.commit()

def fetch_model_history():
    query = "SELECT * FROM model_predictions ORDER BY created_at DESC"
    with get_db_connection() as conn:
        cursor = _exec(conn, query)
        return [dict(row) for row in cursor.fetchall()]

def update_model_prediction_result(prediction_id: int, result: str, home_score: float = None, away_score: float = None):
    query = "UPDATE model_predictions SET result = ?, home_score = ?, away_score = ? WHERE id = ?"
    with get_db_connection() as conn:
        _exec(conn, query, (result, home_score, away_score, prediction_id))
        conn.commit()

def init_transactions_tab():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            user_id TEXT,
            account_id TEXT,
            provider TEXT NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            balance REAL NOT NULL,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            user_id UUID NOT NULL,
            account_id UUID,
            provider TEXT NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            balance REAL NOT NULL,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Transactions table initialized.")

def insert_bet(bet_data: dict):
    query = """
    INSERT OR IGNORE INTO bets 
    (user_id, account_id, provider, date, sport, bet_type, wager, profit, status, description, selection, odds, is_live, is_bonus, raw_text)
    VALUES (:user_id, :account_id, :provider, :date, :sport, :bet_type, :wager, :profit, :status, :description, :selection, :odds, :is_live, :is_bonus, :raw_text)
    """
    with get_db_connection() as conn:
        _exec(conn, query, bet_data)
        conn.commit()

def insert_transaction(txn_data: dict):
    query = """
    INSERT OR IGNORE INTO transactions
    (txn_id, user_id, account_id, provider, date, type, description, amount, balance, raw_data)
    VALUES (:id, :user_id, :account_id, :provider, :date, :type, :description, :amount, :balance, :raw_data)
    """
    with get_db_connection() as conn:
        _exec(conn, query, txn_data)
        conn.commit()

def update_bet_status(bet_id: int, status: str, user_id: str):
    """
    Updates the status and profit of a bet.
    """
    # First, fetch the bet to get wager and odds
    fetch_query = "SELECT wager, odds FROM bets WHERE id = :id AND user_id = :user_id"
    with get_db_connection() as conn:
        cursor = _exec(conn, fetch_query, {"id": bet_id, "user_id": user_id})
        bet = cursor.fetchone()
        if not bet:
            return False
            
        wager = bet['wager']
        odds = bet['odds']
        
        # Calculate new profit
        new_profit = 0.0
        if status == 'WON':
            if odds:
                if odds > 0:
                    multiplier = (odds / 100)
                else:
                    multiplier = (100 / abs(odds))
                new_profit = wager * multiplier
            else:
                new_profit = wager # Default 1:1 if odds missing?
        elif status == 'LOST':
            new_profit = -wager
        elif status == 'PUSH':
            new_profit = 0.0
            
        update_query = """
        UPDATE bets 
        SET status = :status, profit = :profit 
        WHERE id = :id AND user_id = :user_id
        """
        _exec(conn, update_query, {"status": status, "profit": new_profit, "id": bet_id, "user_id": user_id})
        conn.commit()
        return True

def delete_bet(bet_id: int, user_id: str):
    query = "DELETE FROM bets WHERE id = :id AND user_id = :user_id"
    with get_db_connection() as conn:
        _exec(conn, query, {"id": bet_id, "user_id": user_id})
        conn.commit()
        return True

def fetch_all_bets(user_id: str = None):
    if user_id:
        query = "SELECT * FROM bets WHERE user_id = :user_id ORDER BY date DESC"
        params = {"user_id": user_id}
    else:
        query = "SELECT * FROM bets ORDER BY date DESC"
        params = {}
        
    with get_db_connection() as conn:
        cursor = _exec(conn, query, params)
        return [dict(row) for row in cursor.fetchall()]

def fetch_latest_ledger_info():
    query = """
    SELECT provider, balance, date 
    FROM transactions 
    WHERE date = (SELECT MAX(date) FROM transactions t2 WHERE t2.provider = transactions.provider)
    """
    with get_db_connection() as conn:
        cursor = _exec(conn, query)
        return {row['provider']: {'balance': row['balance'], 'date': row['date']} for row in cursor.fetchall()}

def init_player_stats_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS player_stats_ncaam (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT NOT NULL,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            date TEXT, 
            game_gp INTEGER,
            mpg REAL,
            ortg REAL,
            usg REAL,
            efg REAL,
            ts_pct REAL,
            orb_pct REAL,
            drb_pct REAL,
            ast_pct REAL,
            to_pct REAL,
            blk_pct REAL,
            stl_pct REAL,
            ftr REAL,
            pfr REAL,
            three_p_pct REAL,
            two_p_pct REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(player_id, date)
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS player_stats_ncaam (
            id SERIAL PRIMARY KEY,
            player_id TEXT NOT NULL,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            date TEXT, 
            game_gp INTEGER,
            mpg REAL,
            ortg REAL,
            usg REAL,
            efg REAL,
            ts_pct REAL,
            orb_pct REAL,
            drb_pct REAL,
            ast_pct REAL,
            to_pct REAL,
            blk_pct REAL,
            stl_pct REAL,
            ftr REAL,
            pfr REAL,
            three_p_pct REAL,
            two_p_pct REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(player_id, date)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Player stats (NCAAM) table initialized.")

def insert_player_stats(stats: list):
    query = """
    INSERT OR IGNORE INTO player_stats_ncaam
    (player_id, name, team, date, game_gp, mpg, ortg, usg, efg, ts_pct, orb_pct, drb_pct, ast_pct, to_pct, blk_pct, stl_pct, ftr, pfr, three_p_pct, two_p_pct)
    VALUES 
    (:player_id, :name, :team, :date, :games, :mpg, :ortg, :usg, :efg, :ts_pct, :orb_pct, :drb_pct, :ast_pct, :to_pct, :blk_pct, :stl_pct, :ftr, :pfr, :three_p_pct, :two_p_pct)
    """
    with get_db_connection() as conn:
        is_pg = hasattr(conn, 'cursor_factory')
        if is_pg:
            query = query.replace("INSERT OR IGNORE", "INSERT").replace("VALUES", "VALUES") + " ON CONFLICT DO NOTHING"
            import re
            query = re.sub(r':(\w+)', r'%(\1)s', query)
            with conn.cursor() as cur:
                cur.executemany(query, stats)
        else:
            conn.executemany(query, stats)
        conn.commit()
    print(f"Inserted {len(stats)} player stats rows.")

def init_games_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            sport_key TEXT NOT NULL,
            commence_time TEXT,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT,
            winner TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(game_id, sport_key)
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS games (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            sport_key TEXT NOT NULL,
            commence_time TEXT,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT,
            winner TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(game_id, sport_key)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Games history table initialized.")

def upsert_game(game_data: dict):
    winner = None
    if game_data.get('status') in ['completed', 'complete', 'final', 'closed']:
        h = game_data.get('home_score')
        a = game_data.get('away_score')
        if h is not None and a is not None:
             try:
                h = int(h)
                a = int(a)
                if h > a: winner = game_data.get('home_team')
                elif a > h: winner = game_data.get('away_team')
                else: winner = 'Draw'
             except:
                 pass
    game_data['winner'] = winner
    query = """
    INSERT INTO games (game_id, sport_key, commence_time, home_team, away_team, home_score, away_score, status, winner, last_updated)
    VALUES (:game_id, :sport_key, :commence_time, :home_team, :away_team, :home_score, :away_score, :status, :winner, CURRENT_TIMESTAMP)
    ON CONFLICT(game_id, sport_key) DO UPDATE SET
        home_score = excluded.home_score,
        away_score = excluded.away_score,
        status = excluded.status,
        winner = excluded.winner,
        last_updated = CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        _exec(conn, query, game_data)
        conn.commit()

def init_events_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            league TEXT NOT NULL,
            start_time TIMESTAMP,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_event_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(event_id) REFERENCES events(id),
            UNIQUE(provider, provider_event_id)
        );
        CREATE TABLE IF NOT EXISTS game_results (
            event_id TEXT PRIMARY KEY,
            home_score INTEGER,
            away_score INTEGER,
            final_flag BOOLEAN DEFAULT FALSE,
            last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            league TEXT NOT NULL,
            start_time TIMESTAMP,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_providers (
            id SERIAL PRIMARY KEY,
            event_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_event_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(event_id) REFERENCES events(id),
            UNIQUE(provider, provider_event_id)
        );
        CREATE TABLE IF NOT EXISTS game_results (
            event_id TEXT PRIMARY KEY,
            home_score INTEGER,
            away_score INTEGER,
            final_flag BOOLEAN DEFAULT FALSE,
            last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Canonical events tables initialized.")

def upsert_event(event: dict):
    query = """
    INSERT INTO events (id, league, start_time, home_team, away_team, status)
    VALUES (:id, :league, :start_time, :home_team, :away_team, :status)
    ON CONFLICT(id) DO UPDATE SET
        start_time = excluded.start_time,
        status = excluded.status,
        home_team = excluded.home_team,
        away_team = excluded.away_team
    """
    with get_db_connection() as conn:
        _exec(conn, query, event)
        conn.commit()

def upsert_event_provider(mapping: dict):
    query = """
    INSERT INTO event_providers (event_id, provider, provider_event_id)
    VALUES (:event_id, :provider, :provider_event_id)
    ON CONFLICT(provider, provider_event_id) DO NOTHING
    """
    with get_db_connection() as conn:
        _exec(conn, query, mapping)
        conn.commit()

def upsert_game_result(result: dict):
    query = """
    INSERT INTO game_results (event_id, home_score, away_score, final_flag, last_updated_at)
    VALUES (:event_id, :home_score, :away_score, :final_flag, CURRENT_TIMESTAMP)
    ON CONFLICT(event_id) DO UPDATE SET
        home_score = excluded.home_score,
        away_score = excluded.away_score,
        final_flag = excluded.final_flag,
        last_updated_at = CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        _exec(conn, query, result)
        conn.commit()

def init_ingestion_runs_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS provider_ingestion_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            league TEXT,
            run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            target_date TEXT,
            status TEXT NOT NULL,
            items_count INTEGER,
            error_msg TEXT
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS provider_ingestion_runs (
            id SERIAL PRIMARY KEY,
            provider TEXT NOT NULL,
            league TEXT,
            run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            target_date TEXT,
            status TEXT NOT NULL,
            items_count INTEGER,
            error_msg TEXT
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Ingestion logs table initialized.")

def log_ingestion_run(run_data: dict):
    query = """
    INSERT INTO provider_ingestion_runs (provider, league, target_date, status, items_count, error_msg)
    VALUES (:provider, :league, :target_date, :status, :items_count, :error_msg)
    """
    with get_db_connection() as conn:
        _exec(conn, query, run_data)
        conn.commit()

def init_settlement_db():
    db_type = get_db_type()
    # PRE-MIGRATION: Drop old settlement_events if strictly needed or assume we can coexist/alter?
    # Old schema had 'prediction_id'. New has 'leg_id'. We should drop the old one.
    
    # Event Sourcing for Settlement
    # Using simple DROP here for dev transition. In prod we'd alter or backup.
    # Note: We put DROP in SQL execution below.
    
    if db_type == 'sqlite':
        schema = """
        DROP TABLE IF EXISTS settlement_events; 
        CREATE TABLE IF NOT EXISTS settlement_events (
            id TEXT PRIMARY KEY, -- UUID
            bet_id INTEGER NOT NULL,
            leg_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            outcome TEXT NOT NULL, 
            graded_by TEXT DEFAULT 'system',
            grading_version TEXT DEFAULT 'v1',
            inputs_json TEXT, 
            fingerprint TEXT NOT NULL,
            result_revision INTEGER DEFAULT 0,
            graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bet_id) REFERENCES bets(id),
            FOREIGN KEY(leg_id) REFERENCES bet_legs(id),
            FOREIGN KEY(event_id) REFERENCES events_v2(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_settlement_fingerprint ON settlement_events(fingerprint);
        
        CREATE TABLE IF NOT EXISTS model_daily_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            sport TEXT NOT NULL,
            count_bets INTEGER,
            brier_score REAL,
            log_loss REAL,
            roi REAL,
            net_profit REAL,
            ev_total REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport)
        );
        """
        # Execute
        with get_db_connection() as conn:
            conn.executescript(schema)
            conn.commit()
    else:
        # Postgres
        schema_settle = """
        DROP TABLE IF EXISTS settlement_events CASCADE;
        CREATE TABLE IF NOT EXISTS settlement_events (
            id TEXT PRIMARY KEY, -- UUID
            bet_id INTEGER NOT NULL,
            leg_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            graded_by TEXT DEFAULT 'system',
            grading_version TEXT DEFAULT 'v1',
            inputs_json TEXT,
            fingerprint TEXT NOT NULL,
            result_revision INTEGER DEFAULT 0,
            graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bet_id) REFERENCES bets(id),
            FOREIGN KEY(leg_id) REFERENCES bet_legs(id),
            FOREIGN KEY(event_id) REFERENCES events_v2(id)
        );
        """
        # Index separate
        idx_sql = "CREATE UNIQUE INDEX IF NOT EXISTS idx_settlement_fingerprint ON settlement_events(fingerprint);"
        
        schema_metrics = """
        CREATE TABLE IF NOT EXISTS model_daily_metrics (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            sport TEXT NOT NULL,
            count_bets INTEGER,
            brier_score REAL,
            log_loss REAL,
            roi REAL,
            net_profit REAL,
            ev_total REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport)
        );
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_settle)
                cur.execute(idx_sql)
                cur.execute(schema_metrics)
            conn.commit()

    print("Settlement tables initialized (v2).")

def log_settlement_event(event_data: dict):
    query = """
    INSERT INTO settlement_events (prediction_id, event_id, grading_status, calculated_profit, grading_metadata)
    VALUES (:prediction_id, :event_id, :grading_status, :calculated_profit, :grading_metadata)
    """
    with get_db_connection() as conn:
        _exec(conn, query, event_data)
        conn.commit()

def upsert_daily_metrics(metrics: dict):
    query = """
    INSERT INTO model_daily_metrics (date, sport, count_bets, brier_score, log_loss, roi, net_profit, ev_total)
    VALUES (:date, :sport, :count_bets, :brier_score, :log_loss, :roi, :net_profit, :ev_total)
    ON CONFLICT(date, sport) DO UPDATE SET
        count_bets = excluded.count_bets,
        brier_score = excluded.brier_score,
        log_loss = excluded.log_loss,
        roi = excluded.roi,
        net_profit = excluded.net_profit,
        ev_total = excluded.ev_total,
        created_at = CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        _exec(conn, query, metrics)
        conn.commit()

def init_model_registry_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS model_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            version_tag TEXT NOT NULL,
            lifecycle_status TEXT DEFAULT 'experimental',
            config_json TEXT, -- JSONB
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sport, version_tag)
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_version_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            market_type TEXT,
            feature_snapshot_date TIMESTAMP,
            output_win_prob REAL,
            output_cover_prob REAL,
            output_over_prob REAL,
            output_implied_margin REAL,
            output_implied_total REAL,
            output_uncertainty REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(model_version_id) REFERENCES model_versions(id)
        );
        CREATE TABLE IF NOT EXISTS prediction_outcomes (
            prediction_id INTEGER PRIMARY KEY,
            actual_margin REAL,
            actual_total REAL,
            actual_outcome_json TEXT,
            error_margin REAL,
            brier_contribution REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(prediction_id) REFERENCES predictions(id)
        );
        CREATE TABLE IF NOT EXISTS model_health_daily (
            date DATE NOT NULL,
            model_version_id INTEGER NOT NULL,
            league TEXT,
            market_type TEXT,
            metric_name TEXT NOT NULL,
            metric_value REAL,
            sample_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(date, model_version_id, league, market_type, metric_name),
            FOREIGN KEY(model_version_id) REFERENCES model_versions(id)
        );
        """
    else:
        # Postgres
        schema = """
        CREATE TABLE IF NOT EXISTS model_versions (
            id SERIAL PRIMARY KEY,
            sport TEXT NOT NULL,
            version_tag TEXT NOT NULL,
            lifecycle_status TEXT DEFAULT 'experimental',
            config_json JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sport, version_tag)
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id SERIAL PRIMARY KEY,
            model_version_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            market_type TEXT,
            feature_snapshot_date TIMESTAMP,
            output_win_prob REAL,
            output_cover_prob REAL,
            output_over_prob REAL,
            output_implied_margin REAL,
            output_implied_total REAL,
            output_uncertainty REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(model_version_id) REFERENCES model_versions(id)
        );
        CREATE TABLE IF NOT EXISTS prediction_outcomes (
            prediction_id INTEGER PRIMARY KEY,
            actual_margin REAL,
            actual_total REAL,
            actual_outcome_json JSONB,
            error_margin REAL,
            brier_contribution REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(prediction_id) REFERENCES predictions(id)
        );
        CREATE TABLE IF NOT EXISTS model_health_daily (
            date DATE NOT NULL,
            model_version_id INTEGER NOT NULL,
            league TEXT,
            market_type TEXT,
            metric_name TEXT NOT NULL,
            metric_value REAL,
            sample_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(date, model_version_id, league, market_type, metric_name),
            FOREIGN KEY(model_version_id) REFERENCES model_versions(id)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Model Registry tables initialized.")

def register_model_version(sport, tag, config, status='experimental'):
    import json
    if isinstance(config, dict):
        config = json.dumps(config)
        
    query = """
    INSERT INTO model_versions (sport, version_tag, lifecycle_status, config_json)
    VALUES (:sport, :tag, :status, :config)
    ON CONFLICT(sport, version_tag) DO UPDATE SET
        lifecycle_status = excluded.lifecycle_status,
        config_json = excluded.config_json
    RETURNING id
    """
    with get_db_connection() as conn:
        cursor = _exec(conn, query, {"sport": sport, "tag": tag, "status": status, "config": config})
        row = cursor.fetchone()
        conn.commit()
        if row:
            return row[0] # Return ID
        return None

def store_prediction_v2(data: dict):
    # Mapping dict keys to columns
    query = """
    INSERT INTO predictions (
        model_version_id, event_id, league, market_type, feature_snapshot_date, 
        output_win_prob, output_cover_prob, output_over_prob, 
        output_implied_margin, output_implied_total, output_uncertainty
    )
    VALUES (
        :model_version_id, :event_id, :league, :market_type, :feature_snapshot_date,
        :win_prob, :cover_prob, :over_prob,
        :implied_margin, :implied_total, :uncertainty
    )
    RETURNING id
    """
    with get_db_connection() as conn:
        cursor = _exec(conn, query, data)
        row = cursor.fetchone()
        conn.commit()
        return row[0] if row else None

def init_props_parlays_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS bet_legs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bet_id INTEGER NOT NULL,
            event_id TEXT, -- Optional, links to canonical event
            leg_type TEXT NOT NULL, -- MONEYLINE, SPREAD, TOTAL, PLAYER_PROP
            subject_id TEXT, -- Player ID
            market_key TEXT,
            selection TEXT NOT NULL,
            line_value REAL,
            odds_american INTEGER,
            side TEXT, -- HOME, AWAY, OVER, UNDER
            selection_team_id TEXT, -- UUID
            status TEXT DEFAULT 'PENDING',
            link_status TEXT DEFAULT 'PENDING', -- PENDING, LINKED, QUARANTINED
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bet_id) REFERENCES bets(id)
        );
        -- Add hash column to bets if missing (SQLite ALTER constraints are tricky)
        -- We handle this via application logic or full migration if needed.
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS bet_legs (
            id SERIAL PRIMARY KEY,
            bet_id INTEGER NOT NULL,
            event_id TEXT,
            leg_type TEXT NOT NULL,
            subject_id TEXT,
            market_key TEXT,
            selection TEXT NOT NULL,
            line_value REAL,
            odds_american INTEGER,
            side TEXT,
            selection_team_id TEXT,
            status TEXT DEFAULT 'PENDING',
            link_status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bet_id) REFERENCES bets(id)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Prop & Parlay tables initialized.")

def insert_bet_v2(bet_data: dict, legs: list = None):
    # Idempotency check via hash_id
    if 'hash_id' in bet_data:
        check = "SELECT id FROM bets WHERE hash_id = :hash_id"
        with get_db_connection() as conn:
            cur = _exec(conn, check, {"hash_id": bet_data['hash_id']})
            if cur.fetchone():
                print(f"Skipping duplicate bet hash: {bet_data['hash_id']}")
                return None

    query = """
    INSERT INTO bets 
    (user_id, account_id, provider, date, sport, bet_type, wager, profit, status, description, selection, odds, is_live, is_bonus, raw_text, hash_id, is_parlay)
    VALUES (:user_id, :account_id, :provider, :date, :sport, :bet_type, :wager, :profit, :status, :description, :selection, :odds, :is_live, :is_bonus, :raw_text, :hash_id, :is_parlay)
    """
    
    # Return ID for postgres
    if get_db_type() == 'postgres':
        query += " RETURNING id"

    with get_db_connection() as conn:
        cursor = _exec(conn, query, bet_data)
        if get_db_type() == 'postgres':
            bet_id = cursor.fetchone()[0]
        else:
            bet_id = cursor.lastrowid
            
        if legs:
            leg_query = """
            INSERT INTO bet_legs (bet_id, event_id, leg_type, subject_id, market_key, selection, line_value, odds_american, status, link_status, side, selection_team_id)
            VALUES (:bet_id, :event_id, :leg_type, :subject_id, :market_key, :selection, :line_value, :odds_american, :status, :link_status, :side, :selection_team_id)
            """
            for leg in legs:
                leg['bet_id'] = bet_id
                _exec(conn, leg_query, leg)
                
        conn.commit()
        return bet_id

def init_team_metrics_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS bt_team_metrics_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_text TEXT NOT NULL,
            date TEXT NOT NULL,
            adj_off REAL, 
            adj_def REAL,
            adj_tempo REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_text, date)
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS bt_team_metrics_daily (
            id SERIAL PRIMARY KEY,
            team_text TEXT NOT NULL,
            date TEXT NOT NULL,
            adj_off REAL, 
            adj_def REAL,
            adj_tempo REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_text, date)
        );
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Team metrics (NCAAM) table initialized.")

def upsert_team_metrics(metrics: list):
    query = """
    INSERT INTO bt_team_metrics_daily
    (team_text, date, adj_off, adj_def, adj_tempo)
    VALUES (:team_text, :date, :adj_off, :adj_def, :adj_tempo)
    """
    with get_db_connection() as conn:
        is_pg = hasattr(conn, 'cursor_factory')
        if is_pg:
            query = query.replace("INSERT INTO", "INSERT INTO") + " ON CONFLICT (team_text, date) DO UPDATE SET adj_off=excluded.adj_off, adj_def=excluded.adj_def, adj_tempo=excluded.adj_tempo"
            import re
            query = re.sub(r':(\w+)', r'%(\1)s', query)
            with conn.cursor() as cur:
                cur.executemany(query, metrics)
        else:
            query += " ON CONFLICT(team_text, date) DO UPDATE SET adj_off=excluded.adj_off, adj_def=excluded.adj_def, adj_tempo=excluded.adj_tempo"
            conn.executemany(query, metrics)
        conn.commit()

def init_ingestion_backbone_db():
    # This acts as a migration for the existing provider_ingestion_runs table
    db_type = get_db_type()
    
    # 1. Add new columns if missing
    migration_queries = []
    if db_type == 'postgres':
        migration_queries = [
            "ALTER TABLE provider_ingestion_runs ADD COLUMN IF NOT EXISTS run_status TEXT",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN IF NOT EXISTS items_processed INTEGER DEFAULT 0",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN IF NOT EXISTS items_changed INTEGER DEFAULT 0",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN IF NOT EXISTS payload_snapshot_path TEXT",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN IF NOT EXISTS schema_drift_detected BOOLEAN DEFAULT FALSE",
            # Backfill old status to run_status if null
            "UPDATE provider_ingestion_runs SET run_status = status WHERE run_status IS NULL"
        ]
    else:
        # Sqlite limited alter support, mostly append
        migration_queries = [
            "ALTER TABLE provider_ingestion_runs ADD COLUMN run_status TEXT",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN items_processed INTEGER DEFAULT 0",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN items_changed INTEGER DEFAULT 0",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN payload_snapshot_path TEXT",
            "ALTER TABLE provider_ingestion_runs ADD COLUMN schema_drift_detected BOOLEAN DEFAULT FALSE"
        ]

    with get_db_connection() as conn:
        cursor = conn.cursor() if db_type == 'postgres' else conn
        
        for q in migration_queries:
            try:
                if db_type == 'postgres':
                    cursor.execute(q)
                else:
                    cursor.execute(q)
            except Exception as e:
                # Ignore duplicate column errors in SQLite
                # print(f"Migration note: {e}")
                pass
                
        # 2. Add New Tables
        if db_type == 'sqlite':
            schema = """
            CREATE TABLE IF NOT EXISTS events_v2 (
                id TEXT PRIMARY KEY, -- Canonical UUID
                league TEXT NOT NULL,
                season TEXT,
                start_time TIMESTAMP NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                status TEXT NOT NULL,
                venue TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(league, start_time, home_team, away_team)
            );
            CREATE TABLE IF NOT EXISTS event_providers (
                event_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_event_id TEXT NOT NULL,
                last_updated TIMESTAMP,
                PRIMARY KEY(event_id, provider),
                FOREIGN KEY(event_id) REFERENCES events_v2(id)
            );
            """
            conn.executescript(schema)
        else:
            schema = """
            CREATE TABLE IF NOT EXISTS events_v2 (
                id TEXT PRIMARY KEY,
                league TEXT NOT NULL,
                season TEXT,
                start_time TIMESTAMP NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                status TEXT NOT NULL,
                venue TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(league, start_time, home_team, away_team)
            );
            CREATE TABLE IF NOT EXISTS event_providers (
                event_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_event_id TEXT NOT NULL,
                last_updated TIMESTAMP,
                PRIMARY KEY(event_id, provider),
                FOREIGN KEY(event_id) REFERENCES events_v2(id)
            );
            """
            cursor.execute(schema)
            
        conn.commit()
    print("Ingestion Backbone tables initialized/migrated.")

def log_ingestion_run(run_data: dict):
    # Ensure ID is string if UUID
    if 'id' in run_data: run_data['id'] = str(run_data['id'])
    
    # Check if run_status is present, else map
    if 'run_status' not in run_data and 'status' in run_data:
        run_data['run_status'] = run_data['status']
        
    query = """
    INSERT INTO provider_ingestion_runs 
    (provider, league, run_status, items_processed, items_changed, payload_snapshot_path, schema_drift_detected, status)
    VALUES (:provider, :league, :run_status, :items_processed, :items_changed, :payload_snapshot_path, :schema_drift_detected, :run_status)
    """
    # Note: I added 'status' to values to satisfy the NOT NULL constraint of the old table definition if it exists
    
    with get_db_connection() as conn:
        _exec(conn, query, run_data)
        conn.commit()

def init_team_identity_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY, -- UUID
            league TEXT NOT NULL,
            name TEXT NOT NULL,
            abbreviation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS team_provider_map (
            team_id TEXT NOT NULL,
            league TEXT,
            provider TEXT NOT NULL,
            provider_team_id TEXT NOT NULL,
            provider_team_name TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(provider, provider_team_id, league),
            FOREIGN KEY(team_id) REFERENCES teams(id)
        );
        CREATE TABLE IF NOT EXISTS team_aliases (
            team_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source TEXT DEFAULT 'auto',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(team_id) REFERENCES teams(id),
            UNIQUE(team_id, alias)
        );
        -- Index for fast alias lookup
        CREATE INDEX IF NOT EXISTS idx_team_alias ON team_aliases(alias);
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            league TEXT NOT NULL,
            name TEXT NOT NULL,
            abbreviation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS team_provider_map (
            team_id TEXT NOT NULL,
            league TEXT,
            provider TEXT NOT NULL,
            provider_team_id TEXT NOT NULL,
            provider_team_name TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(provider, provider_team_id, league),
            FOREIGN KEY(team_id) REFERENCES teams(id)
        );
        CREATE TABLE IF NOT EXISTS team_aliases (
            team_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source TEXT DEFAULT 'auto',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(team_id) REFERENCES teams(id),
            UNIQUE(team_id, alias)
        );
        CREATE INDEX IF NOT EXISTS idx_team_alias ON team_aliases(alias);
        """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Team Identity tables initialized.")

def migrate_events_v2_schema():
    """
    Add team_id columns to events_v2 if they don't exist.
    """
    alter_queries = [
        "DROP TABLE IF EXISTS event_providers", # Force recreation to fix FK
        "ALTER TABLE events_v2 ADD COLUMN home_team_id TEXT",
        "ALTER TABLE events_v2 ADD COLUMN away_team_id TEXT",
        # "ALTER TABLE event_providers ADD COLUMN last_updated TIMESTAMP" # Handled by recreation
    ]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for q in alter_queries:
            try:
                if get_db_type() == 'sqlite':
                     cursor.execute(q)
                else:
                     cursor.execute(q)
                conn.commit()
                print(f"Executed: {q}")
            except Exception as e:
                # Ignore duplicate column errors
                # print(f"Migration note: {e}")
                conn.rollback()
    
    # Re-create event_providers if dropped or missing
    schema_ep = """
    CREATE TABLE IF NOT EXISTS event_providers (
        event_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        provider_event_id TEXT NOT NULL,
        last_updated TIMESTAMP,
        PRIMARY KEY(provider, provider_event_id),
        UNIQUE(event_id, provider),
        FOREIGN KEY(event_id) REFERENCES events_v2(id)
    );
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(schema_ep)
        conn.commit()

    # Re-create index for uniqueness with IDs
    # SQLite/PG: CREATE UNIQUE INDEX IF NOT EXISTS ...
    # We replace the old constraint? 
    # Old: UNIQUE(league, start_time, home_team, away_team)
    # New: UNIQUE(league, start_time, home_team_id, away_team_id)
    # We can create a new index for lookups.
    idx_sql = "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_v2_canonical ON events_v2(league, start_time, home_team_id, away_team_id)"
    # Fix missing PK/Unique on event_providers if it was created incorrectly
    # Execute Index Creation
    with get_db_connection() as conn:
        try:
            conn.cursor().execute(idx_sql)
            conn.commit()
        except Exception as e:
            # print(f"Index creation note: {e}")
            pass

    print("events_v2 schema migrated.")

def init_game_results_db():
    db_type = get_db_type()
    
    # Force recreation to fix missing columns (Dev Mode)
    # Using specific drop logic
    drop_sql = "DROP TABLE IF EXISTS game_results CASCADE" if db_type == 'postgres' else "DROP TABLE IF EXISTS game_results"

    schema = """
    CREATE TABLE IF NOT EXISTS game_results (
        event_id TEXT PRIMARY KEY,
        home_score INTEGER,
        away_score INTEGER,
        final BOOLEAN DEFAULT FALSE,
        period TEXT,
        status TEXT,
        source_provider TEXT,
        final_at TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(event_id) REFERENCES events_v2(id)
    );
    """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(f"{drop_sql}; {schema}")
        else:
            with conn.cursor() as cur:
                cur.execute(drop_sql)
                cur.execute(schema)
        conn.commit()
    print("Game Results table initialized (Re-created).")

def init_linking_queue_db():
    db_type = get_db_type()
    schema = """
    CREATE TABLE IF NOT EXISTS unmatched_legs_queue (
        leg_id INTEGER PRIMARY KEY,
        reason TEXT,
        candidates_json TEXT, -- JSON list of potential event IDs
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(leg_id) REFERENCES bet_legs(id)
    );
    """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Unmatched Legs Queue initialized.")

def init_model_health_db():
    db_type = get_db_type()
    schema = """
    CREATE TABLE IF NOT EXISTS model_health_daily (
        date TEXT NOT NULL,
        model_version_id TEXT NOT NULL,
        league TEXT NOT NULL,
        market_type TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL NOT NULL,
        sample_size INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(date, model_version_id, league, market_type, metric_name)
    );
    """
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Model Health Daily table initialized.")

def init_model_health_insights_db():
    db_type = get_db_type()
    schema = """
    CREATE TABLE IF NOT EXISTS model_health_insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        summary TEXT,
        anomalies_json TEXT,
        hypothesis TEXT,
        action_items_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date) -- One insight per day per run? Or allows multiple? Let's say one per day usually.
        -- Actually, we might run multiple times. Let's make it APPEND log or use date as key.
        -- User asked for "Store analysis". Let's assume daily log.
    );
    """
    if db_type == 'postgres':
        schema = schema.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id SERIAL PRIMARY KEY")
        
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
    print("Model Health Insights table initialized.")

def store_health_insight(insight: dict, date_str: str):
    import json
    q = """
    INSERT INTO model_health_insights (date, summary, anomalies_json, hypothesis, action_items_json)
    VALUES (:date, :summary, :anomalies, :hypothesis, :actions)
    """
    params = {
        "date": date_str,
        "summary": insight.get("summary", ""),
        "anomalies": json.dumps(insight.get("anomalies", [])),
        "hypothesis": insight.get("hypothesis", ""),
        "actions": json.dumps(insight.get("action_items", []))
    }
    with get_db_connection() as conn:
        _exec(conn, q, params)
        conn.commit()

def init_policy_db():
    db_type = get_db_type()
    
    # 1. market_allowlist
    schema_market = """
    CREATE TABLE IF NOT EXISTS market_allowlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        market_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'SHADOW', -- ENABLED, SHADOW, DISABLED
        max_units_per_day INTEGER DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reason TEXT,
        UNIQUE(league, market_type)
    );
    """
    
    # 2. model_registry
    schema_model = """
    CREATE TABLE IF NOT EXISTS model_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_version TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'SHADOW', -- PRIMARY, SHADOW, DISABLED
        allocation_weight REAL DEFAULT 0.0,
        min_sample_for_promotion INTEGER DEFAULT 150,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # 3. policy_decisions (audit trail)
    schema_audit = """
    CREATE TABLE IF NOT EXISTS policy_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        decision_type TEXT NOT NULL, -- MARKET_UPDATE, MODEL_UPDATE
        target TEXT NOT NULL, -- "NCAAM/Spread" or "v1_basic"
        old_value TEXT,
        new_value TEXT,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    # 4. market_performance_daily
    schema_perf = """
    CREATE TABLE IF NOT EXISTS market_performance_daily (
        date TEXT NOT NULL,
        league TEXT NOT NULL,
        market_type TEXT NOT NULL,
        roi REAL DEFAULT 0.0,
        clv REAL DEFAULT 0.0,
        hit_rate REAL DEFAULT 0.0,
        sample_size INTEGER DEFAULT 0,
        PRIMARY KEY(date, league, market_type)
    );
    """
    
    if db_type == 'postgres':
        schema_market = schema_market.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id SERIAL PRIMARY KEY")
        schema_model = schema_model.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id SERIAL PRIMARY KEY")
        schema_audit = schema_audit.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id SERIAL PRIMARY KEY")
        
    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema_market)
            conn.executescript(schema_model)
            conn.executescript(schema_audit)
            conn.executescript(schema_perf)
        else:
            with conn.cursor() as cur:
                cur.execute(schema_market)
                cur.execute(schema_model)
                cur.execute(schema_audit)
                cur.execute(schema_perf)
        conn.commit()
    print("Policy Control Plane (Allowlist, Registry, Audit) initialized.")
    init_signal_db()

def init_signal_db():
    db_type = get_db_type()
    
    # 1. signal_registry (Meta)
    schema_registry = """
    CREATE TABLE IF NOT EXISTS signal_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_family TEXT NOT NULL UNIQUE, -- e.g. "INJURY_NEWS", "LINEUP_CHANGE"
        status TEXT DEFAULT 'SHADOW', -- ENABLED, SHADOW, DISABLED
        min_confidence REAL DEFAULT 0.0,
        max_adjustment_points REAL DEFAULT 3.0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # 2. signal_performance_daily
    schema_perf = """
    CREATE TABLE IF NOT EXISTS signal_performance_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        signal_family TEXT NOT NULL,
        clv_lift REAL, -- Incremental CLV vs baseline
        roi_lift REAL,
        sample_size INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, signal_family)
    );
    """
    
    if db_type == 'postgres':
         schema_registry = schema_registry.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id SERIAL PRIMARY KEY")
         schema_perf = schema_perf.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id SERIAL PRIMARY KEY")

    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema_registry)
            conn.executescript(schema_perf)
        else:
            with conn.cursor() as cur:
                cur.execute(schema_registry)
                cur.execute(schema_perf)
        conn.commit()
    print("Signal Curation Tables initialized.")

def store_daily_evaluation(metrics: list):
    """
    Store a batch of daily evaluation metrics.
    metrics: List[Dict] with keys: date, model_version_id, league, market_type, metric_name, metric_value, sample_size
    """
    if not metrics:
        return
        
    query = """
    INSERT INTO model_health_daily (
        date, model_version_id, league, market_type, metric_name, metric_value, sample_size
    ) VALUES (
        :date, :model_version_id, :league, :market_type, :metric_name, :metric_value, :sample_size
    ) ON CONFLICT(date, model_version_id, league, market_type, metric_name) DO UPDATE SET
        metric_value = excluded.metric_value,
        sample_size = excluded.sample_size,
        created_at = CURRENT_TIMESTAMP
    """
    
    with get_db_connection() as conn:
        if hasattr(conn, 'executemany'):
             # SQLite
             conn.executemany(query, metrics)
        else:
             # Postgres (psycopg2) usually uses execute_batch or just execute loops for simplicity if volume low.
             # Or standard executemany if compliant.
             # Our _exec wrapper handles single query.
             # For batch, we can loop or use specific cursor method.
             # Simple loop for MVP robustness:
             # Use _exec for each item to handle param style
             for m in metrics:
                 _exec(conn, query, m)
        conn.commit()

def fetch_model_health_daily(date=None, league=None, market_type=None):
    """
    Fetch model health metrics.
    """
    query = "SELECT * FROM model_health_daily"
    params = {}
    conditions = []
    
    if date:
        conditions.append("date = :date")
        params["date"] = date
    if league:
        conditions.append("league = :league")
        params["league"] = league
    if market_type:
        conditions.append("market_type = :market")
        params["market"] = market_type
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    query += " ORDER BY date DESC, model_version_id, league, market_type"
    
    with get_db_connection() as conn:
        cursor = _exec(conn, query, params)
        return [dict(row) for row in cursor.fetchall()]

def init_odds_snapshots_db():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            book TEXT NOT NULL,
            market_type TEXT NOT NULL,
            side TEXT NOT NULL,
            line REAL,
            price REAL NOT NULL,
            captured_at TIMESTAMP NOT NULL,
            captured_bucket TIMESTAMP NOT NULL,
            UNIQUE(event_id, market_type, side, line, book, captured_bucket)
        );
        CREATE INDEX IF NOT EXISTS idx_odds_event ON odds_snapshots(event_id);
        CREATE INDEX IF NOT EXISTS idx_odds_captured ON odds_snapshots(captured_at);
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id SERIAL PRIMARY KEY,
            event_id TEXT NOT NULL,
            book TEXT NOT NULL,
            market_type TEXT NOT NULL,
            side TEXT NOT NULL,
            line DECIMAL(10,1),
            price DECIMAL(10,3) NOT NULL,
            captured_at TIMESTAMP NOT NULL,
            captured_bucket TIMESTAMP NOT NULL,
            UNIQUE(event_id, market_type, side, line, book, captured_bucket)
        );
        CREATE INDEX IF NOT EXISTS idx_odds_event ON odds_snapshots(event_id);
        CREATE INDEX IF NOT EXISTS idx_odds_captured ON odds_snapshots(captured_at);
        """
        
    # Derived Features Table
    schema_features = """
    CREATE TABLE IF NOT EXISTS market_line_features (
        game_id TEXT NOT NULL,
        market_type TEXT NOT NULL, -- SPREAD, TOTAL
        open_line REAL,
        current_line REAL,
        line_movement REAL DEFAULT 0.0,
        volatility REAL DEFAULT 0.0,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(game_id, market_type)
    );
    """

    with get_db_connection() as conn:
        if db_type == 'sqlite':
            conn.executescript(schema)
            conn.executescript(schema_features)
        else:
            with conn.cursor() as cur:
                cur.execute(schema)
                cur.execute(schema_features)
        conn.commit()
    print("Odds Snapshots & Market Features initialized.")

def calc_market_features(game_id: str):
    """
    Computes Open vs Current line movement from odds_snapshots.
    """
    # 1. Get Snapshots
    q = """
    SELECT line, captured_at, market_type 
    FROM odds_snapshots 
    WHERE event_id = :gid 
    ORDER BY captured_at ASC
    """
    with get_db_connection() as conn:
        rows = _exec(conn, q, {"gid": game_id}).fetchall()
        
    if not rows: return
    
    # Group by Market Type
    by_type = {}
    for r in rows:
        mt = r['market_type']
        if mt not in by_type: by_type[mt] = []
        by_type[mt].append(r)
        
    # Calculate Features
    for mt, data in by_type.items():
        if not data: continue
        
        # Open = First chronologically
        open_val = data[0]['line']
        # Current = Last chronologically
        curr_val = data[-1]['line']
        
        movement = curr_val - open_val
        
        # Volatility? (simple stddev placeholder)
        # If we had list of lines: [l for r in data].std()
        
        # Upsert
        uq = """
        INSERT INTO market_line_features (game_id, market_type, open_line, current_line, line_movement)
        VALUES (:gid, :mt, :op, :cur, :mov)
        ON CONFLICT(game_id, market_type) DO UPDATE SET
            open_line = excluded.open_line,
            current_line = excluded.current_line,
            line_movement = excluded.line_movement,
            last_updated = CURRENT_TIMESTAMP
        """
        with get_db_connection() as conn:
            _exec(conn, uq, {
                "gid": game_id,
                "mt": mt,
                "op": open_val,
                "cur": curr_val,
                "mov": movement
            })
            conn.commit()

def get_market_features(game_id: str) -> dict:
    """
    Returns dict: {market_type: {open, current, movement}}
    """
    q = "SELECT * FROM market_line_features WHERE game_id = :gid"
    with get_db_connection() as conn:
        rows = _exec(conn, q, {"gid": game_id}).fetchall()
        return {r['market_type']: dict(r) for r in rows}

def store_odds_snapshots(snapshots: list):
    """
    Store a batch of odds snapshots.
    snapshots: List[Dict] with canonical fields.
    """
    if not snapshots: return
    
    q = """
    INSERT INTO odds_snapshots (
        event_id, book, market_type, side, line, price, captured_at, captured_bucket
    ) VALUES (
        :event_id, :book, :market_type, :side, :line, :price, :captured_at, :captured_bucket
    ) ON CONFLICT(event_id, market_type, side, line, book, captured_bucket) DO NOTHING
    """
    with get_db_connection() as conn:
        is_pg = hasattr(conn, 'cursor_factory')
        if is_pg:
            import re
            # Convert :key to %(key)s
            q = re.sub(r'(?<!:):(\w+)', r'%(\1)s', q)
            # ON CONFLICT DO NOTHING is already in q (mostly), but Postgres needs exact target usually for ON CONFLICT
            # Wait, Postgres does support ON CONFLICT(col1, col2) DO NOTHING.
            # My q already has: ON CONFLICT(event_id, market_type, side, line, book, captured_bucket) DO NOTHING
            # Which is valid for Postgres too if the index exists.
            
        if is_pg:
            with conn.cursor() as cur:
                # In Postgres, use execute_batch for speed or just execute in loop
                # psycopg2.extras.execute_batch(cur, q, snapshots)
                # But to keep dependencies low, loop is fine for now.
                for s in snapshots:
                    cur.execute(q, s)
        else:
            # SQLite
            conn.executemany(q, snapshots)
        conn.commit()
    return len(snapshots)

def get_last_prestart_snapshot(event_id: str, market_type: str):
    """
    Fetches the latest odds snapshots for an event captured before the event start time.
    """
    q = """
    SELECT o.*
    FROM odds_snapshots o
    JOIN events_v2 e ON e.id = o.event_id
    WHERE o.event_id = :event_id
      AND o.market_type = :market_type
      AND o.captured_at <= e.start_time
    ORDER BY o.captured_at DESC
    """
    with get_db_connection() as conn:
        cursor = _exec(conn, q, {"event_id": event_id, "market_type": market_type})
        rows = cursor.fetchall()
        
        # Group by book, side, line to get the very latest set
        latest = {}
        for r in rows:
            key = (r['book'], r['side'], r['line'])
            if key not in latest:
                latest[key] = dict(r)
        
        return list(latest.values())

def fetch_model_health_daily(date: str = None, league: str = None, market_type: str = None):
    """
    Fetch model health metrics for analysis/UI.
    """
    q = "SELECT * FROM model_health_daily WHERE 1=1"
    params = {}
    if date:
        q += " AND date = :date"
        params['date'] = date
    if league:
        q += " AND league = :league"
        params['league'] = league
    if market_type:
        q += " AND market_type = :market_type"
        params['market_type'] = market_type
        
    q += " ORDER BY date DESC, league, market_type"
    
    with get_db_connection() as conn:
        cursor = _exec(conn, q, params)
        return [dict(r) for r in cursor.fetchall()]

def upsert_team_metrics(metrics: list):
    """
    Store batch of team metrics (BartTorvik).
    metrics: List[Dict] with team_text, date, adj_off, adj_def, adj_tempo
    """
    if not metrics: return
    
    q = """
    INSERT INTO bt_team_metrics_daily (
        team_text, date, adj_off, adj_def, adj_tempo
    ) VALUES (
        :team_text, :date, :adj_off, :adj_def, :adj_tempo
    ) ON CONFLICT(team_text, date) DO UPDATE SET
        adj_off = excluded.adj_off,
        adj_def = excluded.adj_def,
        adj_tempo = excluded.adj_tempo,
        created_at = CURRENT_TIMESTAMP
    """
    
    with get_db_connection() as conn:
        if hasattr(conn, 'executemany'): # SQLite
             conn.executemany(q, metrics)
        else: # Postgres simple loop
             for m in metrics:
                 _exec(conn, q, m)
        conn.commit()
    print(f"Upserted {len(metrics)} team metrics.")

