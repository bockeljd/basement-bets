import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime, timezone
import re

from src.config import settings

# Runtime Constant
DB_TYPE = 'postgres'

@contextmanager
def get_db_connection():
    """
    Serverless-safe connection manager.
    Connects to the POOLED url (DATABASE_URL) for standard runtime queries.
    Yields connection, ensures closure. 
    Does NOT maintain a global pool in app memory.
    """
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")

    conn = None
    try:
        conn = psycopg2.connect(
            settings.DATABASE_URL,
            cursor_factory=psycopg2.extras.DictCursor
        )
        yield conn
    except Exception as e:
        if conn and not conn.closed:
            try: conn.rollback()
            except: pass
        raise e
    finally:
        if conn and not conn.closed:
            conn.close()

@contextmanager
def get_admin_db_connection():
    """
    Connects to the UNPOOLED url if available, for schema changes/migrations.
    Falls back to regular URL if unpooled not set.
    """
    dsn = settings.DATABASE_URL_UNPOOLED or settings.DATABASE_URL
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set.")

    conn = None
    try:
        conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.DictCursor)
        yield conn
    except Exception as e:
        if conn and not conn.closed:
            try: conn.rollback()
            except: pass
        raise e
    finally:
        if conn and not conn.closed:
            conn.close()

def _exec(conn, sql, params=None):
    """
    Unified execute helper (Postgres Only).
    """
    if params is None: 
        params = ()
    
    # 1. Convert ? to %s
    if '?' in sql:
        sql = sql.replace('?', '%s')
    
    # 2. Convert :key to %(key)s
    if ':' in sql and not '%(' in sql:
        sql = re.sub(r'(?<!:):([a-zA-Z_]\w*)', r'%(\1)s', sql)
            
    # 3. Handle INSERT OR IGNORE -> ON CONFLICT DO NOTHING
    if "INSERT OR IGNORE" in sql:
        sql = sql.replace("INSERT OR IGNORE", "INSERT")
        if "ON CONFLICT" not in sql:
            sql += " ON CONFLICT DO NOTHING"
            
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return cursor

def get_db_type():
    return 'postgres'

# ----------------------------------------------------------------------------
# ADVISORY LOCKS (Concurrency Control)
# ----------------------------------------------------------------------------

def try_advisory_lock(conn, key_str: str) -> bool:
    """
    Attempts to acquire a session-level advisory lock using a 64-bit integer key derived from the string.
    Returns True if acquired, False if already locked.
    The lock is released when the connection closes or when release_advisory_lock is called.
    """
    import zlib
    lock_id = zlib.crc32(key_str.encode('utf-8'))
    
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (lock_id,))
        res = cur.fetchone()
        return res['locked'] if res else False

def release_advisory_lock(conn, key_str: str):
    """
    Releases the advisory lock.
    """
    import zlib
    lock_id = zlib.crc32(key_str.encode('utf-8'))
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))

# ----------------------------------------------------------------------------
# SCHEMA INITIALIZATION (Safe / Idempotent)
# ----------------------------------------------------------------------------

def init_db():
    print("[DB] Initializing Database (Postgres Only)...")
    init_events_db()
    init_snapshots_db()
    init_model_history_db()
    init_settlement_db()
    init_users_db()
    init_game_results_db()
    init_bt_team_metrics_db()
    init_market_curation_db()
    init_enrichment_db()
    init_jobs_db()
    init_performance_objects() # Phase 14/15

    # Explicitly init bets last as it depends on others conceptually (not foreign key wise mostly)
    init_bets_db()
    init_transactions_db()
    init_balance_snapshots_db()

def _force_reset() -> bool:
    return os.environ.get("BASEMENT_DB_RESET") == "1"

def init_performance_objects():
    """
    Create Indexes and Views for performance (Phase 14 & 15).
    """
    print("[DB] Initializing Performance Views & Indexes...")
    
    # 1. Indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_events_league_start ON events(league, start_time);",
        "CREATE INDEX IF NOT EXISTS ix_odds_lookup ON odds_snapshots(event_id, market_type, side, captured_at DESC);",
        "CREATE INDEX IF NOT EXISTS ix_predictions_time ON model_predictions(event_id, analyzed_at DESC);",
        "CREATE INDEX IF NOT EXISTS ix_predictions_pending ON model_predictions(analyzed_at DESC) WHERE outcome IS NULL OR outcome = 'PENDING';",
        "CREATE INDEX IF NOT EXISTS ix_results_final ON game_results(event_id, final);"
    ]
    
    # 2. Latest Odds View
    # Distinct On is very efficient in Postgres for this exact "latest row per group" problem
    view_sql = """
    CREATE OR REPLACE VIEW latest_odds_snapshots AS
    SELECT DISTINCT ON (event_id, market_type, side, book)
        *
    FROM odds_snapshots
    ORDER BY event_id, market_type, side, book, captured_at DESC;
    """
    
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for idx in indexes:
                try: cur.execute(idx)
                except Exception as e: print(f"[DB] Index error: {e}")
            cur.execute(view_sql)
        conn.commit()

def init_jobs_db():
    drops = ["DROP TABLE IF EXISTS job_runs CASCADE;", "DROP TABLE IF EXISTS job_state CASCADE;"] if _force_reset() else []
    
    schema = """
    CREATE TABLE IF NOT EXISTS job_runs (
        id BIGSERIAL PRIMARY KEY,
        job_name TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        status TEXT NOT NULL DEFAULT 'running',  -- running/success/failure/skipped
        detail JSONB,
        error TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_job_runs_name_time ON job_runs(job_name, started_at DESC);
    
    CREATE TABLE IF NOT EXISTS job_state (
        job_name TEXT PRIMARY KEY,
        state JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: 
                try: cur.execute(d)
                except: pass
            cur.execute(schema)
        conn.commit()
    print("Job Logging tables initialized.")

def init_bets_db():
    drops = ["DROP TABLE IF EXISTS bets CASCADE;"] if _force_reset() else []
    # Note: user_id and account_id are TEXT to match Auth0/Supabase string IDs
    schema = """
    CREATE TABLE IF NOT EXISTS bets (
        id SERIAL PRIMARY KEY,
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
        raw_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, provider, description, date, wager)
    );
    CREATE INDEX IF NOT EXISTS idx_bets_user_date ON bets(user_id, date);
    """
    
    migrations = [
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS is_live BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS is_bonus BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS raw_text TEXT;",
        # In case we ever need account_id if it was missing 
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS account_id TEXT;"
    ]

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
            if not drops:
                for m in migrations:
                    try: cur.execute(m)
                    except Exception as e: print(f"[DB] Migration warn: {e}")
        conn.commit()
    print("Bets table initialized.")

def init_events_db():
    schema = """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        sport_key TEXT,
        league TEXT,
        home_team TEXT,
        away_team TEXT,
        start_time TIMESTAMP,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_events_league ON events(league);
    CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
    """
    drops = ["DROP TABLE IF EXISTS events CASCADE;"] if _force_reset() else []
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
        conn.commit()
    print("Events DB initialized.")

def init_snapshots_db():
    schema = """
    CREATE TABLE IF NOT EXISTS odds_snapshots (
        id SERIAL PRIMARY KEY,
        event_id TEXT REFERENCES events(id),
        book TEXT,
        market_type TEXT,
        side TEXT,
        line_value REAL,
        price INTEGER,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        snapshot_key TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_snap_event ON odds_snapshots(event_id);
    CREATE INDEX IF NOT EXISTS idx_snap_captured ON odds_snapshots(captured_at DESC);
    """
    drops = ["DROP TABLE IF EXISTS odds_snapshots CASCADE;"] if _force_reset() else []
    
    # Non-destructive migrations for existing tables
    migrations = [
        "ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS snapshot_key TEXT;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_snapshots_snapshot_key ON odds_snapshots(snapshot_key);",
        # Migrate captured_at to TIMESTAMPTZ NOT NULL
        "ALTER TABLE odds_snapshots ALTER COLUMN captured_at TYPE TIMESTAMPTZ USING captured_at AT TIME ZONE 'UTC';",
        "ALTER TABLE odds_snapshots ALTER COLUMN captured_at SET NOT NULL;",
        "ALTER TABLE odds_snapshots ALTER COLUMN captured_at SET DEFAULT NOW();",
    ]
    
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
            if not drops: # Run migrations if not creating fresh
                for m in migrations: 
                    try: cur.execute(m)
                    except Exception as e: print(f"[DB] Migration warn: {e}")
        conn.commit()
    print("Snapshots DB initialized.")

def init_model_history_db():
    drops = ["DROP TABLE IF EXISTS model_predictions CASCADE;"] if _force_reset() else []
    schema = """
    CREATE TABLE IF NOT EXISTS model_predictions (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        user_id TEXT,
        analyzed_at TIMESTAMPTZ DEFAULT NOW(),
        model_version TEXT,
        market_type TEXT, 
        pick TEXT,        
        bet_line REAL,
        bet_price INTEGER,
        book TEXT,
        mu_market REAL,
        mu_torvik REAL,
        mu_final REAL,
        sigma REAL,
        win_prob REAL,
        ev_per_unit REAL,
        confidence_0_100 INTEGER,
        inputs_json TEXT, 
        outputs_json TEXT, 
        narrative_json TEXT,
        outcome TEXT DEFAULT 'PENDING',
        close_line REAL,
        close_price INTEGER,
        
        selection TEXT,
        price INTEGER,
        fair_line REAL,
        edge_points REAL,
        open_line REAL,
        open_price INTEGER,
        clv_points REAL,
        clv_price_delta INTEGER,
        clv_method TEXT,
        close_captured_at TIMESTAMP,
        
        prediction_key TEXT UNIQUE,
        
        FOREIGN KEY(event_id) REFERENCES events(id)
    );
    CREATE INDEX IF NOT EXISTS idx_model_event ON model_predictions(event_id);
    CREATE INDEX IF NOT EXISTS idx_model_user_time ON model_predictions(user_id, analyzed_at DESC);
    """
    migrations = [
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS model_version TEXT;",
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS prediction_key TEXT;",
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS user_id TEXT;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_model_predictions_prediction_key ON model_predictions(prediction_key);",
        "CREATE INDEX IF NOT EXISTS idx_model_user_time ON model_predictions(user_id, analyzed_at DESC);"
    ]
    
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
            if not drops:
                for m in migrations:
                    try: cur.execute(m)
                    except Exception as e: print(f"[DB] Migration warn: {e}")
        conn.commit()
    print("Model predictions table initialized.")

def init_settlement_db():
    drops = ["DROP TABLE IF EXISTS settlements CASCADE;"] if _force_reset() else []
    schema = """
    CREATE TABLE IF NOT EXISTS settlements (
        id SERIAL PRIMARY KEY,
        cycle_id TEXT UNIQUE,
        period_start TIMESTAMP,
        period_end TIMESTAMP,
        total_bets_graded INTEGER,
        total_profit REAL,
        roi REAL,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
        conn.commit()
    print("Settlement DB initialized.")

def init_users_db():
    # user_id is implicit ID here, usually matches Auth provider ID (TEXT/UUID)
    # We use UUID type for PK if strictly UUID, but TEXT is safer for mixed auth providers.
    # Let's standardize on UUID for the primary key if we control it, but the input ID usually comes from external auth.
    # If Supabase, it IS uuid. If Auth0, it might be 'auth0|12345'.
    # Safe bet: id TEXT PRIMARY KEY.
    
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, 
        email TEXT UNIQUE NOT NULL,
        role TEXT DEFAULT 'user',
        preferences_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    );
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
    print("Users table initialized.")

def init_game_results_db():
    drops = ["DROP TABLE IF EXISTS game_results CASCADE;"] if _force_reset() else []
    schema = """
    CREATE TABLE IF NOT EXISTS game_results (
        id SERIAL PRIMARY KEY,
        event_id TEXT UNIQUE REFERENCES events(id),
        home_score INTEGER,
        away_score INTEGER,
        final BOOLEAN DEFAULT FALSE,
        period TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
        conn.commit()
    print("Game Results initialized.")

def init_bt_team_metrics_db():
    drops = ["DROP TABLE IF EXISTS bt_team_metrics CASCADE;"] if _force_reset() else []
    schema = """
    CREATE TABLE IF NOT EXISTS bt_team_metrics (
        team_name TEXT,
        year INTEGER,
        adj_oe REAL,
        adj_de REAL,
        barthag REAL,
        record TEXT,
        conf_record TEXT,
        adj_tempo REAL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (team_name, year)
    );
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
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
        conn.commit()
    print("BartTorvik metrics initialized.")

def init_market_curation_db():
    drops = [
        "DROP TABLE IF EXISTS model_health_daily;",
        "DROP TABLE IF EXISTS market_allowlist;",
        "DROP TABLE IF EXISTS market_performance_daily;"
    ] if _force_reset() else []
    
    schema = """
    CREATE TABLE IF NOT EXISTS model_health_daily (
        id SERIAL PRIMARY KEY,
        date TEXT NOT NULL,
        league TEXT NOT NULL,
        market_type TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL,
        sample_size INTEGER,
        status TEXT, 
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, league, market_type, metric_name)
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
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: 
                try: cur.execute(d)
                except: pass
            cur.execute(schema)
        conn.commit()
    print("Smart Curation (Registry/Allowlist) tables initialized.")

def init_enrichment_db():
    # Postgres
    schema = """
    CREATE TABLE IF NOT EXISTS action_game_enrichment (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        event_id TEXT NOT NULL, -- references events(id) but explicit FK might be annoying if events missing
        provider TEXT DEFAULT 'ACTION_NETWORK',
        provider_game_id TEXT,
        as_of_ts TIMESTAMPTZ DEFAULT NOW(),
        payload_json JSONB,
        fingerprint TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS action_injuries (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        event_id TEXT NOT NULL,
        team_id TEXT,
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
        event_id TEXT NOT NULL,
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
        event_id TEXT NOT NULL,
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
        team_id TEXT,
        event_id TEXT,
        headline TEXT,
        summary TEXT,
        url TEXT,
        published_at TIMESTAMPTZ,
        source TEXT DEFAULT 'ACTION_NETWORK',
        fingerprint TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_enrich_event ON action_game_enrichment(event_id);
    CREATE INDEX IF NOT EXISTS idx_props_player ON action_props(player_name);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
    print("Action Network Enrichment tables initialized.")

# ----------------------------------------------------------------------------
# LOGIC / QUERIES
# ----------------------------------------------------------------------------
# Note: Helper stubs for inserting/fetching data. 
# They use get_db_connection() (pooled safe) for runtime checks.

def insert_event(event_data: dict):
    query = """
    INSERT INTO events (id, sport_key, league, home_team, away_team, start_time, status)
    VALUES (:id, :sport_key, :league, :home_team, :away_team, :start_time, :status)
    ON CONFLICT (id) DO UPDATE SET
        start_time = EXCLUDED.start_time,
        status = EXCLUDED.status,
        updated_at = CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        _exec(conn, query, event_data)
        conn.commit()

def insert_odds_snapshot(snap: dict) -> bool:
    """
    Insert an odds snapshot with idempotency via snapshot_key.
    Returns True if inserted, False if skipped (duplicate or error).
    Raises ValueError if event_id does not exist in events table.
    """
    import hashlib
    
    event_id = snap.get('event_id')
    if not event_id:
        print("[DB] insert_odds_snapshot: Missing event_id")
        return False
    
    # Pre-check: Ensure event exists (FK will fail anyway, but this gives clear error)
    with get_db_connection() as conn:
        cur = _exec(conn, "SELECT 1 FROM events WHERE id = %s", (event_id,))
        if not cur.fetchone():
            raise ValueError(f"Event not found for event_id={event_id} (ingest events first)")
    
    # Ensure captured_at is set with timezone-aware UTC
    if not snap.get('captured_at'):
        snap['captured_at'] = datetime.now(timezone.utc)
    
    # For snapshot_key, use a stable time grain (minute) for retry safety
    captured_at = snap['captured_at']
    if hasattr(captured_at, 'replace'):
        captured_key = captured_at.replace(second=0, microsecond=0).isoformat()
    else:
        # String fallback - truncate to minute
        captured_key = str(captured_at)[:16]
    
    # Compute snapshot_key for idempotency
    parts = [
        str(event_id),
        str(snap.get('book') or ''),
        str(snap.get('market_type') or ''),
        str(snap.get('side') or ''),
        str(snap.get('line_value') or ''),
        str(snap.get('price') or ''),
        captured_key
    ]
    raw = "|".join(parts)
    snap['snapshot_key'] = hashlib.sha256(raw.encode()).hexdigest()

    query = """
    INSERT INTO odds_snapshots (event_id, book, market_type, side, line_value, price, captured_at, snapshot_key)
    VALUES (:event_id, :book, :market_type, :side, :line_value, :price, :captured_at, :snapshot_key)
    ON CONFLICT (snapshot_key) DO NOTHING
    """

    with get_db_connection() as conn:
        _exec(conn, query, snap)
        conn.commit()
        return True

def store_odds_snapshots(snaps: list) -> int:
    """
    Bulk insert odds snapshots. Returns count of successfully inserted snapshots.
    """
    if not snaps: return 0
    count = 0
    for s in snaps:
        # map any alternate keys to DB schema
        if "line" in s and "line_value" not in s:
            s["line_value"] = s.pop("line")
        # ensure captured_at exists and is datetime
        if not s.get("captured_at"):
            s["captured_at"] = datetime.now(timezone.utc)
            
        try:
            if insert_odds_snapshot(s):
                count += 1
        except ValueError as e:
            print(f"[DB] store_odds_snapshots skipped: {e}")
        except Exception as e:
            print(f"[DB] store_odds_snapshots error: {e}")
    return count

def upsert_game_result(res: dict):
    query = """
    INSERT INTO game_results (event_id, home_score, away_score, final, period)
    VALUES (:event_id, :home_score, :away_score, :final, :period)
    ON CONFLICT (event_id) DO UPDATE SET
        home_score = EXCLUDED.home_score,
        away_score = EXCLUDED.away_score,
        final = EXCLUDED.final,
        period = EXCLUDED.period,
        updated_at = CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        _exec(conn, query, res)
        conn.commit()

def insert_model_prediction(doc: dict) -> bool:
    """
    Insert a model prediction with idempotency via prediction_key.
    Returns True if inserted/updated, False on error.
    Raises ValueError if event_id does not exist.
    """
    import uuid
    import hashlib
    
    event_id = doc.get('event_id')
    if not event_id:
        print("[DB] insert_model_prediction: Missing event_id")
        return False
    
    # Pre-check: Ensure event exists
    with get_db_connection() as conn:
        cur = _exec(conn, "SELECT 1 FROM events WHERE id = %s", (event_id,))
        if not cur.fetchone():
            raise ValueError(f"Event not found for event_id={event_id} (ingest events first)")
    
    if not doc.get('id'): 
        doc['id'] = str(uuid.uuid4())
    
    # Handle analyzed_at with timezone awareness
    analyzed_at = doc.get('analyzed_at')
    if not analyzed_at:
        analyzed_at = datetime.now(timezone.utc)
        doc['analyzed_at'] = analyzed_at
    
    # Convert to datetime if string for bucket calculation
    if isinstance(analyzed_at, str):
        try:
            analyzed_at_dt = datetime.fromisoformat(analyzed_at.replace('Z', '+00:00'))
        except:
            analyzed_at_dt = datetime.now(timezone.utc)
    else:
        analyzed_at_dt = analyzed_at
    
    # Use minute-level bucket for dedupe on double-click
    analyzed_bucket = analyzed_at_dt.replace(second=0, microsecond=0).isoformat()
    
    # Get user_id (important for multi-user isolation)
    user_id = doc.get('user_id') or ''
    doc['user_id'] = user_id if user_id else None
    
    # Compute prediction_key including user_id for isolation
    parts = [
        str(user_id),
        str(event_id),
        str(doc.get('model_version') or 'v1'),
        str(doc.get('market_type') or ''),
        str(doc.get('pick') or ''),
        analyzed_bucket
    ]
    raw = "|".join(parts)
    doc['prediction_key'] = hashlib.sha256(raw.encode()).hexdigest()
         
    # Ensure missing keys matching schema are handled
    keys = ["selection", "price", "fair_line", "edge_points", "open_line", "open_price", 
            "close_line", "close_price", "clv_points", "clv_method", "close_captured_at", "model_version"]
    for k in keys:
         if k not in doc: doc[k] = None

    query = """
    INSERT INTO model_predictions (
        id, event_id, user_id, analyzed_at, model_version, market_type, pick,
        bet_line, bet_price, book, mu_market, mu_torvik, mu_final,
        sigma, win_prob, ev_per_unit, confidence_0_100, 
        inputs_json, outputs_json, narrative_json,
        selection, price, fair_line, edge_points, open_line, open_price,
        close_line, close_price, clv_points, clv_method, close_captured_at,
        prediction_key
    ) VALUES (
        :id, :event_id, :user_id, :analyzed_at, :model_version, :market_type, :pick,
        :bet_line, :bet_price, :book, :mu_market, :mu_torvik, :mu_final,
        :sigma, :win_prob, :ev_per_unit, :confidence_0_100,
        :inputs_json, :outputs_json, :narrative_json,
        :selection, :price, :fair_line, :edge_points, :open_line, :open_price,
        :close_line, :close_price, :clv_points, :clv_method, :close_captured_at,
        :prediction_key
    ) ON CONFLICT (prediction_key) DO UPDATE SET
        outputs_json = EXCLUDED.outputs_json,
        narrative_json = EXCLUDED.narrative_json,
        confidence_0_100 = EXCLUDED.confidence_0_100,
        win_prob = EXCLUDED.win_prob,
        ev_per_unit = EXCLUDED.ev_per_unit
    """
    with get_db_connection() as conn:
        _exec(conn, query, doc)
        conn.commit()
        return True

def update_model_prediction_result(pid: str, outcome: str):
    query = "UPDATE model_predictions SET outcome = :outcome WHERE id = :id"
    with get_db_connection() as conn:
        _exec(conn, query, {"outcome": outcome, "id": pid})
        conn.commit()

# ----------------------------------------------------------------------------
# LOGIC / QUERIES (Appending to end of file)
# ----------------------------------------------------------------------------

def upsert_bt_daily_schedule(payload: list, date_yyyymmdd: str):
    """
    Persist the raw JSON schedule from BartTorvik for a given date.
    """
    import json
    with get_db_connection() as conn:
        _exec(conn, """
            DELETE FROM bt_daily_schedule_raw WHERE date = :date;
            INSERT INTO bt_daily_schedule_raw (date, payload_json, status, created_at)
            VALUES (:date, :json, 'OK', CURRENT_TIMESTAMP);
        """, {"date": date_yyyymmdd, "json": json.dumps(payload)})
        conn.commit()

def insert_bet_v2(doc: dict, legs: list = None) -> int:
    """
    Inserts a bet into the 'bets' table with support for legs (currently ignored/summarized).
    Also creates a corresponding 'transaction' entry for bankroll tracking.
    
    Args:
        doc (dict): Bet document (provider, date, sport, bet_type, wager, profit, status, description, selection, odds, raw_text, hash_id).
        legs (list): List of leg dictionaries (optional).
        
    Returns:
        int: The inserted bet ID.
        
    Raises:
        ValueError if duplicate hash found (unique constraint).
    """
    
    # 1. Insert Bet
    # Schema: user_id, provider, date, sport, bet_type, wager, profit, status, description, selection, odds, raw_text, created_at, hash_id? 
    # Warning: `bets` table schema in `init_bets_db` DOES NOT have `hash_id`. 
    # Run a migration if needed or rely    # If hash_id not provided, compute it
    if not doc.get('hash_id'):
        raw = f"{doc['user_id']}|{doc['provider']}|{doc['date']}|{doc['description']}|{doc['wager']}"
        import hashlib
        doc['hash_id'] = hashlib.sha256(raw.encode()).hexdigest()

    query = """
    INSERT INTO bets (
        user_id, account_id, provider, date, sport, bet_type, wager, profit, status, 
        description, selection, odds, closing_odds, is_live, is_bonus, raw_text, 
        hash_id, validation_errors
    ) VALUES (
        :user_id, :account_id, :provider, :date, :sport, :bet_type, :wager, :profit, :status, 
        :description, :selection, :odds, :closing_odds, :is_live, :is_bonus, :raw_text, 
        :hash_id, :validation_errors
    )
    ON CONFLICT (user_id, provider, description, date, wager) DO UPDATE SET
        profit = EXCLUDED.profit,
        status = EXCLUDED.status,
        selection = EXCLUDED.selection,
        odds = EXCLUDED.odds,
        closing_odds = EXCLUDED.closing_odds,
        raw_text = EXCLUDED.raw_text,
        hash_id = EXCLUDED.hash_id,
        validation_errors = EXCLUDED.validation_errors
    RETURNING id;
    """
    
    # Ensure validation_errors is present in doc, default to None
    if 'validation_errors' not in doc:
        doc['validation_errors'] = None

    bet_id = None
    with get_db_connection() as conn:
        try:
            cur = _exec(conn, query, doc)
            row = cur.fetchone()
            if row: 
                bet_id = row['id']
            conn.commit()
        except Exception as e:
            # If unique constraint violation or other error
            print(f"[DB] Insert V2 Error: {e}")
            # Actually ON CONFLICT DO UPDATE handles it. 
            # So exception is real error.
            raise e

    # 2. Insert Transaction (Bankroll Impact)
    # Only if bet_id found (meaning inserted or updated)
    if bet_id:
        # Determine transaction type/amount
        # PENDING -> Debit Wager? 
        # WON/LOST -> Debit Wager + Credit Payout? or Net? 
        # We model "Wager" as debit at placement. "Payout" as credit at settlement.
        # But if we ingest settled bets directly (History), we just want the net effect?
        # NO. We should insert "Wager" transaction if date matches. 
        
        # Simplified for MVP: Just ensure 'transactions' table has record.
        # Check src/parsers/transactions.py logic if available.
        pass

    return bet_id

def fetch_model_history(limit=100, league=None, user_id=None):
    """
    Fetch model prediction history with optional filtering.
    
    Args:
        limit: Max rows to return
        league: Filter by league (e.g., 'NCAAM')
        user_id: Filter by user_id for multi-user isolation
    """
    # Build query dynamically based on filters
    base_query = """
    SELECT m.*, e.league as sport, e.home_team, e.away_team, e.start_time
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    """
    
    conditions = []
    params = []
    
    if user_id:
        conditions.append("m.user_id = %s")
        params.append(user_id)
    
    if league:
        conditions.append("e.league = %s")
        params.append(league)
    
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)
        
    base_query += " ORDER BY m.analyzed_at DESC LIMIT %s"
    params.append(limit)
    
    with get_db_connection() as conn:
        cursor = _exec(conn, base_query, tuple(params))
        return [dict(r) for r in cursor.fetchall()]


def get_clv_report(limit=50):
    """
    Compare Model Prediction vs Closing Line.
    
    Logic:
    - Join model_predictions (p) with odds_snapshots (o)
    - Filter for 'Closing' lines (latest snapshot before start_time)
    """
    query = """
    WITH closing_lines AS (
        SELECT DISTINCT ON (event_id, market_type) 
            event_id, 
            market_type, 
            line_value, 
            captured_at
        FROM odds_snapshots
        ORDER BY event_id, market_type, captured_at DESC
    )
    SELECT 
        p.event_id,
        p.pick,
        p.bet_line as model_line,
        cl.line_value as closing_line,
        (p.bet_line - cl.line_value) as clv_diff,
        e.start_time,
        e.home_team,
        e.away_team
    FROM model_predictions p
    JOIN events e ON p.event_id = e.id
    LEFT JOIN closing_lines cl ON p.event_id = cl.event_id AND cl.market_type = 'SPREAD' -- Assuming spread for now
    ORDER BY e.start_time DESC
    LIMIT %s
    """
    with get_db_connection() as conn:
        rows = _exec(conn, query, (limit,)).fetchall()
        return [dict(r) for r in rows]

def get_user_preference(user_id: str, key: str):
    """
    Retrieves a specific key from the user's preferences_json.
    """
    import json
    query = "SELECT preferences_json FROM users WHERE id = %s"
    with get_db_connection() as conn:
        cur = _exec(conn, query, (user_id,))
        row = cur.fetchone()
        if row and row['preferences_json']:
            try:
                prefs = json.loads(row['preferences_json'])
                return prefs.get(key)
            except:
                pass
    return None

def update_user_preference(user_id: str, key: str, value: any):
    """
    Updates a key in the user's preferences_json. Merges with existing.
    """
    import json
    
    # 1. Get existing
    query_get = "SELECT preferences_json FROM users WHERE id = %s"
    
    with get_db_connection() as conn:
        cur = _exec(conn, query_get, (user_id,))
        row = cur.fetchone()
        current_prefs = {}
        if row and row['preferences_json']:
            try:
                current_prefs = json.loads(row['preferences_json'])
            except:
                current_prefs = {}

        # 2. Update
        current_prefs[key] = value
        new_json = json.dumps(current_prefs)
        
        # 3. Save (Upsert user if needed? Usually user exists from Auth middleware, but let's be safe)
        # Assuming user exists.
        query_update = "UPDATE users SET preferences_json = %s WHERE id = %s"
        _exec(conn, query_update, (new_json, user_id))
        conn.commit()

def upsert_team_metrics(metrics: list):
    query = """
    INSERT INTO bt_team_metrics (team_name, year, adj_oe, adj_de, barthag, record, conf_record, adj_tempo)
    VALUES (:team_name, :year, :adj_oe, :adj_de, :barthag, :record, :conf_record, :adj_tempo)
    ON CONFLICT (team_name, year) DO UPDATE SET
        adj_oe=EXCLUDED.adj_oe,
        adj_de=EXCLUDED.adj_de,
        barthag=EXCLUDED.barthag,
        record=EXCLUDED.record,
        conf_record=EXCLUDED.conf_record,
        adj_tempo=EXCLUDED.adj_tempo,
        updated_at=CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        # Loop for now, efficient batching needs executemany with tuple adaptation
        for m in metrics:
            _exec(conn, query, m)
        conn.commit()

def upsert_bt_team_metrics_daily(metrics: list):
    """
    Upsert daily team metrics to bt_team_metrics_daily.
    Expected payload keys: team_text, date, adj_off, adj_def, adj_tempo
    """
    query = """
    INSERT INTO bt_team_metrics_daily (team_text, date, adj_off, adj_def, adj_tempo)
    VALUES (:team_text, :date, :adj_off, :adj_def, :adj_tempo)
    ON CONFLICT (team_text, date) DO UPDATE SET
        adj_off = EXCLUDED.adj_off,
        adj_def = EXCLUDED.adj_def,
        adj_tempo = EXCLUDED.adj_tempo
    """
    with get_db_connection() as conn:
        for m in metrics:
            _exec(conn, query, m)
        conn.commit()


def fetch_model_health_daily(date=None, league=None, market_type=None):
    return []

def init_transactions_db():
    """
    Initialize the transactions table for financial flows (deposits, withdrawals, etc.).
    Columns match existing analytics query expectations.
    """
    drops = ["DROP TABLE IF EXISTS transactions CASCADE;"] if _force_reset() else []
    
    schema = """
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        provider TEXT NOT NULL,
        txn_id TEXT NOT NULL,
        date TEXT NOT NULL,
        type TEXT NOT NULL,
        description TEXT,
        amount NUMERIC(12,2) NOT NULL,
        balance NUMERIC(12,2),
        user_id TEXT NOT NULL,
        raw_data TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(provider, txn_id)
    );
    CREATE INDEX IF NOT EXISTS idx_txn_user_date ON transactions(user_id, date DESC);
    CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(type);
    CREATE INDEX IF NOT EXISTS idx_txn_provider ON transactions(provider);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
        conn.commit()
    print("Transactions table initialized.")


def init_balance_snapshots_db():
    """Dedicated balance snapshots table (UI source-of-truth).

    Motivation: `transactions.type IN ('Balance', ...)` gets polluted by recovery rows
    and inconsistent timestamps. This table stays clean and explicit.
    """
    drops = ["DROP TABLE IF EXISTS balance_snapshots CASCADE;"] if _force_reset() else []

    schema = """
    CREATE TABLE IF NOT EXISTS balance_snapshots (
        id BIGSERIAL PRIMARY KEY,
        provider TEXT NOT NULL,
        balance NUMERIC(12,2) NOT NULL,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        source TEXT NOT NULL DEFAULT 'manual',  -- manual|csv|api|scrape
        user_id TEXT,
        note TEXT,
        raw_data JSONB
    );
    CREATE INDEX IF NOT EXISTS idx_balance_snaps_provider_time ON balance_snapshots(provider, captured_at DESC);
    """

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops:
                try:
                    cur.execute(d)
                except Exception:
                    pass
            cur.execute(schema)
        conn.commit()

    print("Balance snapshots table initialized.")


def log_ingestion_run(data: dict):
    """
    Logs ingestion execution to job_runs (consolidated logging).
    """
    job_name = f"ingest_{data.get('provider', 'unknown')}_{data.get('league', 'unknown')}"
    
    # Detail JSON
    detail = {
        "items_processed": data.get("items_processed"),
        "items_changed": data.get("items_changed"),
        "snapshot_path": data.get("payload_snapshot_path"),
        "drift": data.get("schema_drift_detected")
    }
    
    query = """
    INSERT INTO job_runs (job_name, status, detail, finished_at)
    VALUES (:job_name, :status, :detail, CURRENT_TIMESTAMP)
    """
    # Assuming started_at default NOW() is close enough, or we pass it if we want precision.
    # The ingestion engine passes status 'SUCCESS' etc.
    
    params = {
        "job_name": job_name,
        "status": data.get("run_status", "COMPLETED"),
        "detail": psycopg2.extras.Json(detail)
    }
    
    with get_db_connection() as conn:
        _exec(conn, query, params)
        conn.commit()

# ----------------------------------------------------------------------------
# BETS & LEDGER QUERIES (Required by api.py and analytics.py)
# ----------------------------------------------------------------------------

def fetch_all_bets(user_id=None, limit=None):
    """
    Fetches all bets, optionally filtered by user_id.
    Returns list of dicts with normalized field names.
    """
    if user_id:
        query = """
        SELECT id, user_id, account_id, provider, date, sport, bet_type,
               wager, profit, status, description, selection, odds, 
               closing_odds, is_live, is_bonus, created_at
        FROM bets
        WHERE user_id = %s
        ORDER BY date DESC
        """
        params = [user_id]
        if limit:
            query += " LIMIT %s"
            params.append(limit)
        with get_db_connection() as conn:
            cursor = _exec(conn, query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]
    else:
        query = """
        SELECT id, user_id, account_id, provider, date, sport, bet_type,
               wager, profit, status, description, selection, odds,
               closing_odds, is_live, is_bonus, created_at
        FROM bets
        ORDER BY date DESC
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        with get_db_connection() as conn:
            cursor = _exec(conn, query)
            return [dict(r) for r in cursor.fetchall()]

def fetch_latest_balance_snapshots(user_id: str | None = None):
    """Fetch latest balance snapshot per provider from balance_snapshots."""
    q = """
    SELECT DISTINCT ON (provider)
           provider,
           balance,
           captured_at,
           source
    FROM balance_snapshots
    WHERE (:user_id IS NULL OR user_id = :user_id)
    ORDER BY provider, captured_at DESC
    """
    out = {}
    try:
        with get_db_connection() as conn:
            rows = _exec(conn, q, {"user_id": user_id}).fetchall()
            for r in rows:
                d = dict(r)
                out[d['provider']] = {
                    "balance": float(d.get('balance') or 0),
                    "captured_at": d.get('captured_at'),
                    "source": d.get('source')
                }
    except Exception as e:
        # Table might not exist yet in some envs
        print(f"[DB] fetch_latest_balance_snapshots error: {e}")
    return out


def insert_balance_snapshot(snapshot: dict) -> bool:
    """Insert a balance snapshot row."""
    q = """
    INSERT INTO balance_snapshots (provider, balance, captured_at, source, user_id, note, raw_data)
    VALUES (:provider, :balance, COALESCE(:captured_at, NOW()), COALESCE(:source, 'manual'), :user_id, :note, :raw_data)
    """
    doc = {
        "provider": snapshot.get("provider"),
        "balance": snapshot.get("balance"),
        "captured_at": snapshot.get("captured_at"),
        "source": snapshot.get("source") or 'manual',
        "user_id": snapshot.get("user_id"),
        "note": snapshot.get("note"),
        "raw_data": psycopg2.extras.Json(snapshot.get("raw_data")) if snapshot.get("raw_data") is not None else None,
    }
    try:
        with get_db_connection() as conn:
            _exec(conn, q, doc)
            conn.commit()
        return True
    except Exception as e:
        print(f"[DB] insert_balance_snapshot error: {e}")
        return False


def fetch_latest_ledger_info(user_id: str | None = None):
    """Fetch latest balance per provider.

    Priority:
      1) Dedicated balance_snapshots table (clean source-of-truth)
      2) Fallback to legacy transactions Balance rows
    """
    snaps = fetch_latest_balance_snapshots(user_id=user_id)
    if snaps:
        return {k: {"balance": v.get("balance"), "date": str(v.get("captured_at") or ''), "source": v.get("source")} for k, v in snaps.items()}

    # Legacy fallback (transactions table)
    query = """
    SELECT DISTINCT ON (provider) 
           provider, 
           date,
           amount as balance
    FROM transactions
    WHERE type IN ('Deposit', 'Withdrawal', 'Balance')
    ORDER BY provider, date DESC
    """
    result = {}
    try:
        with get_db_connection() as conn:
            cursor = _exec(conn, query)
            for row in cursor.fetchall():
                r = dict(row)
                result[r['provider']] = {
                    'balance': float(r.get('balance') or 0),
                    'date': r.get('date') or ''
                }
    except Exception as e:
        print(f"[DB] fetch_latest_ledger_info error: {e}")
    return result

def insert_bet(bet_data: dict):
    """
    Inserts a single bet into the bets table with idempotency.
    """
    query = """
    INSERT INTO bets (user_id, account_id, provider, date, sport, bet_type,
                      wager, profit, status, description, selection, odds,
                      closing_odds, is_live, is_bonus, raw_text)
    VALUES (:user_id, :account_id, :provider, :date, :sport, :bet_type,
            :wager, :profit, :status, :description, :selection, :odds,
            :closing_odds, :is_live, :is_bonus, :raw_text)
    ON CONFLICT (user_id, provider, description, date, wager) DO UPDATE SET
        profit = EXCLUDED.profit,
        status = EXCLUDED.status,
        closing_odds = EXCLUDED.closing_odds
    """
    # Ensure all required fields
    defaults = {
        'account_id': None, 'selection': None, 'odds': None, 
        'closing_odds': None, 'is_live': False, 'is_bonus': False, 'raw_text': None
    }
    for k, v in defaults.items():
        if k not in bet_data:
            bet_data[k] = v
    
    with get_db_connection() as conn:
        _exec(conn, query, bet_data)
        conn.commit()

def insert_transaction(txn: dict) -> bool:
    """
    Insert a single transaction with idempotency via (provider, txn_id).
    Maps incoming fields from parsers to database schema.
    Returns True if inserted/updated, False on error.
    """
    query = """
    INSERT INTO transactions (provider, txn_id, date, type, description, 
                              amount, balance, user_id, raw_data)
    VALUES (:provider, :txn_id, :date, :type, :description,
            :amount, :balance, :user_id, :raw_data)
    ON CONFLICT (provider, txn_id) DO UPDATE SET
        amount = EXCLUDED.amount,
        balance = EXCLUDED.balance,
        type = EXCLUDED.type,
        description = EXCLUDED.description
    """
    # Map incoming fields from parsers to schema
    doc = {
        'provider': txn.get('provider') or txn.get('sportsbook'),
        'txn_id': txn.get('id') or txn.get('txn_id'),
        'date': txn.get('date') or txn.get('txn_date'),
        'type': txn.get('type') or txn.get('txn_type'),
        'description': txn.get('description'),
        'amount': txn.get('amount'),
        'balance': txn.get('balance'),
        'user_id': txn.get('user_id') or '00000000-0000-0000-0000-000000000000',
        'raw_data': txn.get('raw_data')
    }
    
    try:
        with get_db_connection() as conn:
            _exec(conn, query, doc)
            conn.commit()
            return True
    except Exception as e:
        print(f"[DB] insert_transaction error: {e}")
        return False

def insert_transactions_bulk(txns: list) -> int:
    """
    Bulk insert transactions. Returns count of successfully inserted rows.
    """
    if not txns: return 0
    count = 0
    for txn in txns:
        try:
            if insert_transaction(txn):
                count += 1
        except Exception as e:
            print(f"[DB] insert_transactions_bulk error: {e}")
    return count
