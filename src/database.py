import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime
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
    Attempts to acquire a transaction-level advisory lock using a 64-bit integer key derived from the string.
    Returns True if acquired, False if already locked.
    """
    import zlib
    # Simple consistent hashing: CRC32 is 32-bit, signed.
    # Postgres pg_try_advisory_lock accepts bigint (64-bit).
    # We can use CRC32 safely.
    lock_id = zlib.crc32(key_str.encode('utf-8'))
    
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s) AS locked", (lock_id,))
        # Wait, pg_try_advisory_xact_lock automatically releases at end of transaction.
        # This is safer for serverless if we wrap job in a transaction block.
        # If we want session level (manual release), use pg_try_advisory_lock.
        # Given we use context manager `get_db_connection` which closes connection (ending session),
        # session locks are auto-released on close.
        # Transaction locks are auto-released on commit/rollback.
        # Let's use session lock so we can control scope explicitly if needed, but connection close is the safety net.
        
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
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
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
        captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        snapshot_key TEXT UNIQUE -- Enforce idempotency
    );
    CREATE INDEX IF NOT EXISTS idx_snap_event ON odds_snapshots(event_id);
    """
    drops = ["DROP TABLE IF EXISTS odds_snapshots CASCADE;"] if _force_reset() else []
    
    # Non-destructive migration for existing tables
    migrations = [
        "ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS snapshot_key TEXT;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_snapshots_snapshot_key ON odds_snapshots(snapshot_key);"
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
        analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        
        prediction_key TEXT UNIQUE, -- Enforce idempotency per run strategy
        
        FOREIGN KEY(event_id) REFERENCES events(id)
    );
    CREATE INDEX IF NOT EXISTS idx_model_event ON model_predictions(event_id);
    """
    migrations = [
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS model_version TEXT;",
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS prediction_key TEXT;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_model_predictions_prediction_key ON model_predictions(prediction_key);"
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

def insert_odds_snapshot(snap: dict):
    # Compute snapshot_key for idempotency
    import hashlib
    # Key components: event_id, book, market_type, side, line_value, price, captured_at
    # Note: If captured_at varies by millisecond, this might be too strict. 
    # Usually captured_at comes from provider or is set at consistent time.
    # If snap doesn't have captured_at, we set it now? 
    # Usually database defaults, but for key gen we need it.
    
    # Assuming the caller provides meaningful data.
    # If 'captured_at' is missing, do we generate it? 
    # If we generate it here, repeated calls generate different times -> different keys -> duplicates.
    # For true idempotency, 'captured_at' should be provided by the source or we rely on a coarser grain (minute).
    # MVP: Include it if present, else ignore time in key (risky)? 
    # Or assume caller is responsible for providing stable 'captured_at' if they retry.
    
    parts = [
        str(snap.get('event_id')),
        str(snap.get('book')),
        str(snap.get('market_type')),
        str(snap.get('side')),
        str(snap.get('line_value')),
        str(snap.get('price')),
        str(snap.get('captured_at') or '') # If empty, consistent empty
    ]
    raw = "|".join(parts)
    snap['snapshot_key'] = hashlib.sha256(raw.encode()).hexdigest()

    query = """
    INSERT INTO odds_snapshots (event_id, book, market_type, side, line_value, price, captured_at, snapshot_key)
    VALUES (:event_id, :book, :market_type, :side, :line_value, :price, :captured_at, :snapshot_key)
    ON CONFLICT (snapshot_key) DO NOTHING
    """
    # Ensure captured_at is in snap if it wasn't
    if 'captured_at' not in snap:
        # If we didn't use it in key, letting DB default is fine.
        # But we used it in key (as ''), so passing None lets DB default? 
        # No, 'VALUES' needs it.
        # Let's pass None if missing, relying on DB DEFAULT CURRENT_TIMESTAMP? 
        # But then the inserted row has a timestamp, the key had ''.
        # If we re-run, we generate '' again, and match key.
        # So we just need to ensure the DB insert succeeds.
        snap['captured_at'] = None 

    with get_db_connection() as conn:
        _exec(conn, query, snap)
        conn.commit()

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

def insert_model_prediction(doc: dict):
    import uuid
    import hashlib
    if not doc.get('id'): doc['id'] = str(uuid.uuid4())
    
    # Compute prediction_key
    # (event_id, model_version, analyzed_at)
    # analyzed_at should be stable if re-running same analysis logic time? 
    # Actually, usually analysis is "now". Re-running means "new analysis".
    # But if we want to dedupe "accidental double clicks", we can key by minute?
    # Or if we want to version by (event, model, date).
    # Let's use (event_id, model_version, market_type, pick, analyzed_at).
    
    analyzed_at = doc.get('analyzed_at')
    if not analyzed_at:
        # Default to now if missing, but we need consistency for key?
        from datetime import datetime
        analyzed_at = datetime.utcnow().isoformat()
        doc['analyzed_at'] = analyzed_at
        
    parts = [
        str(doc.get('event_id')),
        str(doc.get('model_version') or 'v1'),
        str(doc.get('market_type')),
        str(doc.get('pick')),
        str(analyzed_at)
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
        id, event_id, analyzed_at, model_version, market_type, pick,
        bet_line, bet_price, book, mu_market, mu_torvik, mu_final,
        sigma, win_prob, ev_per_unit, confidence_0_100, 
        inputs_json, outputs_json, narrative_json,
        selection, price, fair_line, edge_points, open_line, open_price,
        close_line, close_price, clv_points, clv_method, close_captured_at,
        prediction_key
    ) VALUES (
        :id, :event_id, :analyzed_at, :model_version, :market_type, :pick,
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

def update_model_prediction_result(pid: str, outcome: str):
    query = "UPDATE model_predictions SET outcome = :outcome WHERE id = :id"
    with get_db_connection() as conn:
        _exec(conn, query, {"id": pid, "outcome": outcome})
        conn.commit()

def fetch_model_history(limit=100):
    query = """
    SELECT m.*, e.league as sport, e.home_team, e.away_team, e.start_time
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    ORDER BY m.analyzed_at DESC
    LIMIT %s
    """
    with get_db_connection() as conn:
        cursor = _exec(conn, query, (limit,))
        return [dict(r) for r in cursor.fetchall()]

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

def fetch_model_health_daily(date=None, league=None, market_type=None):
    return []

def init_transactions_tab(): pass # Deprecated?
def init_linking_queue_db(): pass
def init_model_health_db(): pass
def init_model_health_insights_db(): pass
def init_policy_db(): pass
def init_ingestion_runs_db(): pass
def init_smart_curation_db(): init_market_curation_db() 
