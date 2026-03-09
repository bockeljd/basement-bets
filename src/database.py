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
    Falls back to regular URL if unpooled not set or fails.
    """
    # Use UNPOOLED if it looks different from DATABASE_URL (pooled),
    # but fallback to regular URL if unpooled not set or fails.
    dsn = settings.DATABASE_URL_UNPOOLED or settings.DATABASE_URL
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set.")

    conn = None
    try:
        conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.DictCursor)
        yield conn
    except psycopg2.OperationalError as e:
        # Fallback to pooled DATABASE_URL if UNPOOLED fails (e.g. auth issues on certain hosts)
        if settings.DATABASE_URL_UNPOOLED and settings.DATABASE_URL and settings.DATABASE_URL_UNPOOLED != settings.DATABASE_URL:
            try:
                conn = psycopg2.connect(settings.DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
                yield conn
            except Exception:
                # If fallback also fails, re-raise the original OperationalError
                raise e
        else:
            # If no fallback option, re-raise the original OperationalError
            raise e
    except Exception as e:
        # For any other exception, re-raise it
        raise e
    finally:
        if conn and not conn.closed:
            conn.close()

def _exec(conn, sql, params=None):
    """Unified execute helper (Postgres Only).

    Supports:
    - positional params: tuple/list
    - named params: dict (psycopg2 pyformat %(name)s)

    Also converts common placeholder styles.
    """
    if params is None:
        params = ()

    # 1. Convert ? to %s
    if '?' in sql:
        sql = sql.replace('?', '%s')

    # 2. Convert :key to %(key)s (but avoid postgres casts ::)
    # IMPORTANT: only do this when params is a dict (named params).
    # Otherwise colons inside string literals like 'action:ncaam:%' will get mangled.
    if isinstance(params, dict) and ':' in sql and not '%(' in sql:
        sql = re.sub(r'(?<!:):([a-zA-Z_]\w*)', r'%(\1)s', sql)

    # 3. Handle INSERT OR IGNORE -> ON CONFLICT DO NOTHING
    if "INSERT OR IGNORE" in sql:
        sql = sql.replace("INSERT OR IGNORE", "INSERT")
        if "ON CONFLICT" not in sql:
            sql += " ON CONFLICT DO NOTHING"

    cursor = conn.cursor()

    # If params is dict, psycopg2 expects a mapping; if it's a list/tuple, sequence.
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

from src.database_council_signals import init_council_signals_db

def init_agent_traces_db():
    drops = ["DROP TABLE IF EXISTS agent_traces CASCADE;"] if _force_reset() else []
    schema = """
    CREATE TABLE IF NOT EXISTS agent_traces (
        id BIGSERIAL PRIMARY KEY,
        run_id TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        task_description TEXT NOT NULL,
        details JSONB,
        timestamp TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_agent_traces_run_id ON agent_traces(run_id);
    CREATE INDEX IF NOT EXISTS idx_agent_traces_agent_name ON agent_traces(agent_name);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
        conn.commit()
    print("Agent Traces table initialized.")

def init_db():
    print("[DB] Initializing Database (Postgres Only)...")
    init_events_db()
    init_snapshots_db()
    init_daily_top_picks_db()
    init_model_history_db()
    init_settlement_db()
    init_users_db()
    init_game_results_db()
    init_bt_team_metrics_db()
    init_market_curation_db()
    init_enrichment_db()
    init_jobs_db()
    init_performance_objects() # Phase 14/15
    init_ncaam_net_rankings_db()
    init_council_signals_db()
    init_agent_traces_db()

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
        event_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, provider, description, date, wager)
    );
    CREATE INDEX IF NOT EXISTS idx_bets_user_date ON bets(user_id, date);
    """

    migrations = [
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS is_live BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS is_bonus BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS raw_text TEXT;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS event_text TEXT;",  # parsed matchup for UI (reduces need to ship raw_text)
        # In case we ever need account_id if it was missing
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS account_id TEXT;",
        # Sportsbook-native id for strong dedupe (e.g. FanDuel BET ID: O/...)
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS external_id TEXT;",
        # Unique index for external_id when present
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bets_user_provider_external_id ON bets(user_id, provider, external_id) WHERE external_id IS NOT NULL;",
        # Audit trail for inline edits
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS updated_by TEXT;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS update_note TEXT;",

        # Lossless normalization fields (keep raw provider data)
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS status_raw TEXT;",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS date_raw TEXT;",
        # Canonical ET day for reliable reporting
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS date_et DATE;",
        "CREATE INDEX IF NOT EXISTS idx_bets_user_date_et ON bets(user_id, date_et);",

        # Provenance / ingest source tagging
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS source TEXT;",
        "CREATE INDEX IF NOT EXISTS idx_bets_source ON bets(source);",
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


def init_dk_ingest_db() -> None:
    """
    Additive schema for the DK automated ingest pipeline.
    Safe to call multiple times (all statements are idempotent).
    Does NOT alter or drop any existing tables/columns.
    """
    stmts = [
        # --- book_ingest_runs: one row per scrape attempt ---
        """
        CREATE TABLE IF NOT EXISTS book_ingest_runs (
            id              BIGSERIAL PRIMARY KEY,
            book            TEXT NOT NULL,
            account_id      TEXT NULL,
            run_started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            run_finished_at TIMESTAMPTZ NULL,
            status          TEXT NOT NULL,
            count_parsed    INT NOT NULL DEFAULT 0,
            inserted        INT NOT NULL DEFAULT 0,
            updated         INT NOT NULL DEFAULT 0,
            message         TEXT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_book_ingest_runs_book_start
        ON book_ingest_runs (book, run_started_at DESC)
        """,
        # --- Extend sync_jobs with DK_INGEST columns (existing rows unaffected) ---
        "ALTER TABLE sync_jobs ADD COLUMN IF NOT EXISTS job_type TEXT",
        "ALTER TABLE sync_jobs ADD COLUMN IF NOT EXISTS payload_json JSONB",
        """
        CREATE INDEX IF NOT EXISTS idx_sync_jobs_status_created
        ON sync_jobs (status, requested_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_sync_jobs_type_status_created
        ON sync_jobs (job_type, status, requested_at)
        """,
        # --- Safe idempotency index on bets.external_id (may already exist) ---
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bets_user_provider_external_id
        ON bets (user_id, provider, external_id)
        WHERE external_id IS NOT NULL
        """,
    ]

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for stmt in stmts:
                try:
                    cur.execute(stmt.strip())
                except Exception as e:
                    print(f"[DB] init_dk_ingest_db warn: {e}")
        conn.commit()
    print("[DB] DK ingest schema initialized.")


def init_events_db():
    schema = """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        sport_key TEXT,
        league TEXT,
        home_team TEXT,
        away_team TEXT,
        -- Store in UTC with timezone so ET conversions are reliable.
        start_time TIMESTAMPTZ,
        status TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_events_league ON events(league);
    CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
    """

    drops = ["DROP TABLE IF EXISTS events CASCADE;"] if _force_reset() else []

    # Non-destructive migrations
    migrations = [
        # Convert legacy TIMESTAMP (assumed UTC) -> TIMESTAMPTZ
        "ALTER TABLE events ALTER COLUMN start_time TYPE TIMESTAMPTZ USING start_time AT TIME ZONE 'UTC';",
        "ALTER TABLE events ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC';",
        "ALTER TABLE events ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC';",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS sport_key TEXT;",
    ]

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops:
                cur.execute(d)
            cur.execute(schema)
            if not drops:
                for m in migrations:
                    try:
                        cur.execute(m)
                    except Exception as e:
                        print(f"[DB] Migration warn (events): {e}")
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
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        snapshot_key TEXT UNIQUE
    );
    """
    drops = ["DROP TABLE IF EXISTS odds_snapshots CASCADE;"] if _force_reset() else []

    # Non-destructive migrations for existing tables
    migrations = [
        "ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS snapshot_key TEXT;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_snapshots_snapshot_key ON odds_snapshots(snapshot_key);",
        "ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();",
        "ALTER TABLE odds_snapshots ALTER COLUMN created_at SET NOT NULL;",
        "ALTER TABLE odds_snapshots ALTER COLUMN captured_at TYPE TIMESTAMPTZ USING captured_at AT TIME ZONE 'UTC';",
        "ALTER TABLE odds_snapshots ALTER COLUMN captured_at SET NOT NULL;",
        "ALTER TABLE odds_snapshots ALTER COLUMN captured_at SET DEFAULT NOW();",
        # Indexes
        "CREATE INDEX IF NOT EXISTS idx_snap_event ON odds_snapshots(event_id);",
        "CREATE INDEX IF NOT EXISTS idx_snap_captured ON odds_snapshots(captured_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_snap_created ON odds_snapshots(created_at DESC);",
    ]

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops: cur.execute(d)
            cur.execute(schema)
            if not drops: 
                for m in migrations:
                    try: cur.execute(m)
                    except Exception as e: print(f"[DB] Migration warn (snapshots): {e}")
        conn.commit()
    print("Snapshots DB initialized.")

def init_daily_top_picks_db():
    """Derived cache of Top Pick per event per ET day (built by background job)."""
    drops = ["DROP TABLE IF EXISTS daily_top_picks CASCADE;"] if _force_reset() else []
    schema = """
    CREATE TABLE IF NOT EXISTS daily_top_picks (
      date_et DATE NOT NULL,
      event_id TEXT NOT NULL,
      league TEXT NOT NULL DEFAULT 'NCAAM',
      computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      model_version TEXT,
      is_actionable BOOLEAN NOT NULL DEFAULT FALSE,
      reason TEXT,
      rec_json JSONB,
      context_json JSONB,
      PRIMARY KEY(date_et, event_id)
    );
    CREATE INDEX IF NOT EXISTS ix_daily_top_picks_date_league ON daily_top_picks(date_et, league);
    """
    migrations = [
      "ALTER TABLE daily_top_picks ADD COLUMN IF NOT EXISTS league TEXT DEFAULT 'NCAAM';",
      "ALTER TABLE daily_top_picks ADD COLUMN IF NOT EXISTS computed_at TIMESTAMPTZ DEFAULT NOW();",
      "ALTER TABLE daily_top_picks ADD COLUMN IF NOT EXISTS model_version TEXT;",
      "ALTER TABLE daily_top_picks ADD COLUMN IF NOT EXISTS is_actionable BOOLEAN DEFAULT FALSE;",
      "ALTER TABLE daily_top_picks ADD COLUMN IF NOT EXISTS reason TEXT;",
      "ALTER TABLE daily_top_picks ADD COLUMN IF NOT EXISTS rec_json JSONB;",
      "ALTER TABLE daily_top_picks ADD COLUMN IF NOT EXISTS context_json JSONB;",
      "CREATE INDEX IF NOT EXISTS ix_daily_top_picks_date_league ON daily_top_picks(date_et, league);",
    ]

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for d in drops:
                cur.execute(d)
            cur.execute(schema)
            if not drops:
                for m in migrations:
                    try:
                        cur.execute(m)
                    except Exception as e:
                        print(f"[DB] daily_top_picks migration warn: {e}")
        conn.commit()


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
        context_json JSONB,
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
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS context_json JSONB;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_model_predictions_prediction_key ON model_predictions(prediction_key);",
        # If older data had NULL keys, cleanup job should backfill first; this is best-effort.
        "ALTER TABLE model_predictions ALTER COLUMN prediction_key SET NOT NULL;",
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
        torvik_rank INTEGER,
        record TEXT,
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
    # Normalize start_time to tz-aware UTC for consistent ET reporting.
    try:
        st = event_data.get('start_time')
        if isinstance(st, str):
            # Accept both Z and offset formats
            st_dt = datetime.fromisoformat(st.replace('Z', '+00:00'))
            if st_dt.tzinfo is None:
                st_dt = st_dt.replace(tzinfo=timezone.utc)
            event_data['start_time'] = st_dt.astimezone(timezone.utc)
        elif isinstance(st, datetime):
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            event_data['start_time'] = st.astimezone(timezone.utc)
    except Exception:
        pass

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
    Uses a single connection + execute_values for efficiency.
    """
    if not snaps: return 0
    import hashlib

    # Prepare rows in Python - compute snapshot_key without hitting DB
    rows = []
    for s in snaps:
        event_id = s.get('event_id')
        if not event_id:
            continue
        if "line" in s and "line_value" not in s:
            s["line_value"] = s.pop("line")
        if not s.get("captured_at"):
            s["captured_at"] = datetime.now(timezone.utc)

        captured_at = s['captured_at']
        if hasattr(captured_at, 'replace'):
            captured_key = captured_at.replace(second=0, microsecond=0).isoformat()
        else:
            captured_key = str(captured_at)[:16]

        parts = [
            str(event_id),
            str(s.get('book') or ''),
            str(s.get('market_type') or ''),
            str(s.get('side') or ''),
            str(s.get('line_value') or ''),
            str(s.get('price') or ''),
            captured_key
        ]
        snapshot_key = hashlib.sha256("|".join(parts).encode()).hexdigest()

        rows.append((
            event_id,
            s.get('book'),
            s.get('market_type'),
            s.get('side'),
            s.get('line_value'),
            s.get('price'),
            captured_at,
            snapshot_key
        ))

    if not rows:
        return 0

    sql = """
    INSERT INTO odds_snapshots (event_id, book, market_type, side, line_value, price, captured_at, snapshot_key)
    VALUES %s
    ON CONFLICT (snapshot_key) DO NOTHING
    """
    try:
        with get_db_connection() as conn:
            from psycopg2.extras import execute_values
            cur = conn.cursor()
            execute_values(cur, sql, rows, page_size=200)
            count = cur.rowcount
            conn.commit()
            return count
    except Exception as e:
        print(f"[DB] store_odds_snapshots bulk error: {e}")
        return 0

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

    # Get user_id (important for multi-user isolation)
    user_id = doc.get('user_id') or ''
    doc['user_id'] = user_id if user_id else None

    # Compute prediction_key deterministically so reruns do not create duplicates.
    # Keyed by the *bet identity* (event/model/market/side/line/price/book/user).
    # IMPORTANT: do NOT include a day/time bucket; events are unique, and including
    # a bucket can create duplicates across reruns/timezones.
    parts = [
        str(user_id),
        str(event_id),
        str(doc.get('model_version') or 'v1'),
        str(doc.get('market_type') or ''),
        str(doc.get('pick') or ''),
        str(doc.get('bet_line') if doc.get('bet_line') is not None else ''),
        str(doc.get('bet_price') if doc.get('bet_price') is not None else ''),
        str(doc.get('book') or ''),
    ]
    raw = "|".join(parts)
    doc['prediction_key'] = hashlib.sha256(raw.encode()).hexdigest()

    # Ensure missing keys matching schema are handled
    keys = ["selection", "price", "fair_line", "edge_points", "open_line", "open_price",
            "close_line", "close_price", "clv_points", "clv_method", "close_captured_at", "model_version", "context_json"]
    for k in keys:
         if k not in doc: doc[k] = None

    query = """
    INSERT INTO model_predictions (
        id, event_id, user_id, analyzed_at, model_version, market_type, pick,
        bet_line, bet_price, book, mu_market, mu_torvik, mu_final,
        sigma, win_prob, ev_per_unit, confidence_0_100,
        inputs_json, outputs_json, narrative_json, context_json,
        selection, price, fair_line, edge_points, open_line, open_price,
        close_line, close_price, clv_points, clv_method, close_captured_at,
        prediction_key
    ) VALUES (
        :id, :event_id, :user_id, :analyzed_at, :model_version, :market_type, :pick,
        :bet_line, :bet_price, :book, :mu_market, :mu_torvik, :mu_final,
        :sigma, :win_prob, :ev_per_unit, :confidence_0_100, 
        :inputs_json, :outputs_json, :narrative_json, :context_json,
        :selection, :price, :fair_line, :edge_points, :open_line, :open_price,
        :close_line, :close_price, :clv_points, :clv_method, :close_captured_at,
        :prediction_key
    ) ON CONFLICT (prediction_key) DO UPDATE SET
        analyzed_at = EXCLUDED.analyzed_at,
        outputs_json = EXCLUDED.outputs_json,
        narrative_json = EXCLUDED.narrative_json,
        context_json = COALESCE(EXCLUDED.context_json, model_predictions.context_json),
        confidence_0_100 = EXCLUDED.confidence_0_100,
        win_prob = EXCLUDED.win_prob,
        ev_per_unit = EXCLUDED.ev_per_unit,
        selection = EXCLUDED.selection,
        price = EXCLUDED.price,
        fair_line = EXCLUDED.fair_line,
        edge_points = EXCLUDED.edge_points,
        open_line = EXCLUDED.open_line,
        open_price = EXCLUDED.open_price,
        bet_line = EXCLUDED.bet_line,
        bet_price = EXCLUDED.bet_price,
        book = EXCLUDED.book,
        market_type = EXCLUDED.market_type,
        pick = EXCLUDED.pick
    """
    try:
        with get_db_connection() as conn:
            _exec(conn, query, doc)
            conn.commit()
            return True
    except Exception as e:
        # Self-heal schema drift in production: context_json column may not exist yet.
        msg = str(e)
        if 'context_json' in msg and ('does not exist' in msg or 'UndefinedColumn' in msg):
            try:
                with get_admin_db_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute("ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS context_json JSONB;")
                    conn2.commit()
                # Retry once
                with get_db_connection() as conn3:
                    _exec(conn3, query, doc)
                    conn3.commit()
                    return True
            except Exception as e2:
                print(f"[DB] insert_model_prediction migration+retry failed: {e2}")
                return False
        print(f"[DB] insert_model_prediction error: {e}")
        return False

def update_model_prediction_result(pid: str, outcome: str):
    query = "UPDATE model_predictions SET outcome = :outcome WHERE id = :id"
    with get_db_connection() as conn:
        _exec(conn, query, {"outcome": outcome, "id": pid})
        conn.commit()


def ensure_recommended_slates_tables():
    """Create tables used to persist the exact slate that was *recommended to the user*.

    This allows grading/analytics to match the Telegram recommendations instead of
    "whatever model_predictions exist for the day".
    """
    sql = """
    CREATE TABLE IF NOT EXISTS recommended_slates (
      id TEXT PRIMARY KEY,
      league TEXT NOT NULL,
      date_et TEXT NOT NULL,
      source TEXT NOT NULL, -- e.g. 'cached' (daily_top_picks) or 'full' (predict_today_v2)
      created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS recommended_slate_items (
      slate_id TEXT NOT NULL REFERENCES recommended_slates(id) ON DELETE CASCADE,
      prediction_id TEXT NOT NULL,
      rank INTEGER,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      PRIMARY KEY(slate_id, prediction_id)
    );

    -- Forward-compatible metadata so we can re-link / audit slates even if prediction ids drift.
    ALTER TABLE recommended_slate_items ADD COLUMN IF NOT EXISTS event_id TEXT;
    ALTER TABLE recommended_slate_items ADD COLUMN IF NOT EXISTS selection TEXT;
    ALTER TABLE recommended_slate_items ADD COLUMN IF NOT EXISTS bet_price INTEGER;
    ALTER TABLE recommended_slate_items ADD COLUMN IF NOT EXISTS bet_line REAL;
    ALTER TABLE recommended_slate_items ADD COLUMN IF NOT EXISTS market_type TEXT;

    CREATE INDEX IF NOT EXISTS ix_reco_slates_date ON recommended_slates(league, date_et, created_at DESC);
    CREATE INDEX IF NOT EXISTS ix_reco_items_slate ON recommended_slate_items(slate_id, rank);
    CREATE INDEX IF NOT EXISTS ix_reco_items_event ON recommended_slate_items(event_id);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
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

def _sync_transaction_for_bet(bet_id, doc=None):
    """
    Helper to upsert a transaction record reflecting the financial impact of a bet.
    If doc is None or incomplete, fetches from DB.
    """
    try:
        from src.database import insert_transaction, get_db_connection, _exec

        # If doc is missing or lacks key fields, fetch from DB
        if not doc or not all(k in doc for k in ('provider', 'wager', 'status')):
             with get_db_connection() as conn:
                 row = _exec(conn, "SELECT * FROM bets WHERE id=%s", (bet_id,)).fetchone()
                 if row:
                     # Convert row to dict
                     doc = dict(row)
                     # Ensure date is string
                     if hasattr(doc['date'], 'strftime'):
                         doc['date'] = doc['date'].strftime("%Y-%m-%d")
                 else:
                     print(f"[DB] Bet {bet_id} not found for transaction sync.")
                     return

        txn_amount = 0.0
        status_up = str(doc.get("status", "")).upper()

        # Use wager from doc (float)
        try:
            wager = float(doc.get("wager", 0))
        except:
            wager = 0.0

        try:
            profit = float(doc.get("profit", 0))
        except:
            profit = 0.0

        if status_up in ["PENDING", "OPEN", "AT RISK"]:
            txn_amount = -1 * wager
        elif status_up in ["LOST"]:
             txn_amount = -1 * wager
        elif status_up in ["WON"]:
             # Won: Amount is Net Profit
             txn_amount = profit
        elif status_up in ["PUSH", "VOID"]:
             txn_amount = 0.0

        # Adjustment handling
        if "Adjustment" in str(doc.get("bet_type", "")) or "Adjustment" in str(doc.get("provider", "")):
             txn_amount = profit

        txn_doc = {
            "provider": doc.get('provider'),
            "txn_id": f"bet_{bet_id}",
            "date": doc.get('date'),
            "type": "Bet" if txn_amount <= 0 else "Payout",
            "description": f"Bet: {doc.get('description')} ({doc.get('bet_type')})",
            "amount": txn_amount,
            "user_id": doc.get('user_id'),
            "raw_data": f"Linked to Bet ID {bet_id}"
        }
        insert_transaction(txn_doc)
    except Exception as e:
         print(f"[DB] Failed to auto-create transaction for bet {bet_id}: {e}")



def update_bet_status(bet_id: int, status: str, user_id: str | None = None) -> bool:
    """Update bet status for a user's bet.

    Important: for manual/open bets, profit is often 0 while pending. When a bet is marked LOST,
    we must set profit = -wager (if profit is missing/0) so bankroll math reflects the loss.
    """
    st = (status or '').upper()
    if st not in ('WON', 'LOST', 'PUSH', 'PENDING'):
        return False
    q = """
    UPDATE bets
    SET status=%s
    WHERE id=%s AND (%s IS NULL OR user_id=%s)
    """
    try:
        with get_db_connection() as conn:
            cur = _exec(conn, q, (st, int(bet_id), user_id, user_id))

            # Ensure profit reflects settlement for common manual workflows
            if st == 'LOST':
                _exec(conn, """
                    UPDATE bets
                    SET profit = -1 * COALESCE(NULLIF(wager,0), wager)
                    WHERE id=%s
                      AND (%s IS NULL OR user_id=%s)
                      AND COALESCE(profit, 0) = 0
                      AND COALESCE(wager, 0) > 0
                """, (int(bet_id), user_id, user_id))
            elif st in ('PUSH', 'VOID'):
                _exec(conn, """
                    UPDATE bets
                    SET profit = 0
                    WHERE id=%s
                      AND (%s IS NULL OR user_id=%s)
                      AND profit IS NULL
                """, (int(bet_id), user_id, user_id))

            conn.commit()
            success = bool(cur.rowcount and cur.rowcount > 0)

        if success:
            _sync_transaction_for_bet(bet_id)

        return success
    except Exception as e:
        print(f"[DB] update_bet_status error: {e}")
        return False

def bulk_update_bet_status(bet_ids: list[int], status: str, user_id: str | None = None) -> int:
    """Update status for multiple bets and sync their transactions."""
    st = (status or '').upper()
    if st not in ('WON', 'LOST', 'PUSH', 'PENDING'):
        return 0
    q = "UPDATE bets SET status=%s WHERE id=ANY(%s) AND (%s IS NULL OR user_id=%s)"
    try:
        with get_db_connection() as conn:
            # Postgres ANY expects a list/tuple for the second param
            cur = _exec(conn, q, (st, list(bet_ids), user_id, user_id))
            conn.commit()
            count = cur.rowcount

        if count > 0:
            for bid in bet_ids:
                try:
                    _sync_transaction_for_bet(bid)
                except:
                    pass
        return count
    except Exception as e:
        print(f"[DB] bulk_update_bet_status error: {e}")
        return 0

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

    # Strong dedupe: if we have a sportsbook-native external_id, upsert by that.
    external_id = doc.get('external_id')

    if external_id:
        with get_db_connection() as conn:
            # 1) Try find existing
            cur = _exec(
                conn,
                """
                SELECT id FROM bets
                WHERE user_id=%s AND provider=%s AND external_id=%s
                LIMIT 1;
                """,
                (doc.get('user_id'), doc.get('provider'), external_id),
            )
            row = cur.fetchone()
            if row and row.get('id'):
                bet_id = row['id']
                _exec(
                    conn,
                    """
                    UPDATE bets SET
                        account_id=%s,
                        date=%s,
                        sport=%s,
                        bet_type=%s,
                        wager=%s,
                        profit=%s,
                        status=%s,
                        description=%s,
                        selection=%s,
                        odds=%s,
                        closing_odds=%s,
                        is_live=%s,
                        is_bonus=%s,
                        raw_text=%s,
                        event_text=%s
                    WHERE id=%s
                    """,
                    (
                        doc.get('account_id'), doc.get('date'), doc.get('sport'), doc.get('bet_type'),
                        doc.get('wager'), doc.get('profit'), doc.get('status'), doc.get('description'),
                        doc.get('selection'), doc.get('odds'), doc.get('closing_odds'), doc.get('is_live'),
                        doc.get('is_bonus'), doc.get('raw_text'), doc.get('event_text'), bet_id
                    ),
                )
                conn.commit()

                # Link transaction
                _sync_transaction_for_bet(bet_id, doc)

                return bet_id
            conn.commit()

    query = """
    INSERT INTO bets (
        user_id, account_id, provider, date, sport, bet_type, wager, profit, status,
        description, selection, odds, closing_odds, is_live, is_bonus, raw_text, event_text,
        external_id, validation_errors, source
    ) VALUES (
        :user_id, :account_id, :provider, :date, :sport, :bet_type, :wager, :profit, :status,
        :description, :selection, :odds, :closing_odds, :is_live, :is_bonus, :raw_text, :event_text,
        :external_id, :validation_errors, :source
    )
    ON CONFLICT (user_id, provider, description, date, wager) DO UPDATE SET
        profit = EXCLUDED.profit,
        status = EXCLUDED.status,
        selection = EXCLUDED.selection,
        odds = EXCLUDED.odds,
        closing_odds = EXCLUDED.closing_odds,
        raw_text = EXCLUDED.raw_text,
        event_text = COALESCE(EXCLUDED.event_text, bets.event_text),
        external_id = COALESCE(EXCLUDED.external_id, bets.external_id),
        validation_errors = EXCLUDED.validation_errors,
        source = COALESCE(EXCLUDED.source, bets.source)
    RETURNING id;
    """

    # event_text is a lightweight, UI-friendly matchup string we persist at ingest time
    # so we don't need to ship raw_text to the client (reduces Neon egress).
    def _extract_event_text(d: dict) -> str | None:
        """Extract a clean matchup like "Maryland @ Minnesota".

        Important: avoid appending the pick/line (e.g. "Minnesota -3.5").
        """
        def _clean_team_side(x: str) -> str:
            x = (x or '').strip()
            # Remove trailing line/total fragments and odds.
            x = re.split(r"\s+[+\---]\d+(?:\.\d+)?\b", x, maxsplit=1)[0]
            x = re.split(r"\s+\b(over|under)\b\s*\d+(?:\.\d+)?\b", x, flags=re.IGNORECASE, maxsplit=1)[0]
            x = re.split(r"\s+\bml\b", x, flags=re.IGNORECASE, maxsplit=1)[0]
            x = re.split(r"\s+\|", x, maxsplit=1)[0]
            x = re.sub(r"\s+", " ", x).strip()
            # Collapse duplicated tokens like "Minnesota Minnesota"
            x = re.sub(r"\b([A-Za-z]{3,})\s+\1\b", r"\1", x, flags=re.IGNORECASE)
            return x.strip()

        try:
            raw_text = str(d.get('raw_text') or '')
            description = str(d.get('description') or '')
            selection = str(d.get('selection') or '')

            # 1) Best: find an explicit matchup line in raw_text
            for src in (raw_text, description, selection):
                if not src:
                    continue
                for ln in str(src).splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    if ('@' in ln) or re.search(r"\b(vs\.?|versus)\b", ln, re.IGNORECASE):
                        m = re.search(r"(.+?)\s*(?:@|vs\.?|versus)\s*(.+)$", ln, flags=re.IGNORECASE)
                        if m:
                            a = _clean_team_side(m.group(1))
                            b = _clean_team_side(m.group(2))
                            if a and b:
                                return f"{a} @ {b}"[:160]

            # 2) Fallback: regex over combined text
            s = "\n".join([raw_text, description, selection])
            s = re.sub(r"\s+", " ", s).strip()
            if not s:
                return None
            m = re.search(r"(.+?)\s*(?:@|vs\.?|versus)\s*(.+?)(?:\s*\||\s*$)", s, flags=re.IGNORECASE)
            if not m:
                return None
            a = _clean_team_side(m.group(1))
            b = _clean_team_side(m.group(2))
            if a and b:
                return f"{a} @ {b}"[:160]
        except Exception:
            return None
        return None

    if 'event_text' not in doc or not doc.get('event_text'):
        doc['event_text'] = _extract_event_text(doc)

    # Ensure validation_errors is present in doc, default to None
    if 'validation_errors' not in doc:
        doc['validation_errors'] = None

    # Provenance
    if 'source' not in doc:
        # Best-effort default: if sportsbook-native id exists, it's from a sportsbook-sourced ingest.
        doc['source'] = 'sportsbook_id' if doc.get('external_id') else 'unknown'

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
        _sync_transaction_for_bet(bet_id, doc)

    return bet_id

def fetch_model_history(limit=100, league=None, user_id=None, recommended_only: bool = False, dedupe: bool = True, lookback_days: int = 120):
    """Fetch model prediction history.

    Notes:
    - When recommended_only=True, we enforce server-side gates so History reflects only bettable recs.
    - When dedupe=True, we keep only the most recent recommendation per (event_id, market_type)
      to avoid repeats from reruns/regrades.
    """

    conditions = []
    params = []

    if user_id:
        # Many legacy model_predictions rows were created without a user_id.
        # In single-user mode, treat NULL/empty user_id as belonging to the current user.
        conditions.append("(m.user_id = %s OR m.user_id IS NULL OR m.user_id = '')")
        params.append(user_id)

    if league:
        conditions.append("e.league = %s")
        params.append(league)

    if recommended_only:
        # Server-side definition of "recommended" to keep History tab clean.
        # Mirrors UI gates: must be actionable (selection present), non-AUTO, real pick, and EV gate.
        conditions.append("COALESCE(m.ev_per_unit, 0) >= 0.02")
        conditions.append("m.market_type IS NOT NULL")
        conditions.append("UPPER(m.market_type) <> 'AUTO'")
        conditions.append("m.pick IS NOT NULL")
        conditions.append("UPPER(m.pick) <> 'NONE'")
        conditions.append("m.selection IS NOT NULL")
        conditions.append("TRIM(m.selection) <> ''")
        conditions.append("m.selection <> '-'")

        # Performance/UX: History should be recent-ish; also prevents DISTINCT ON from scanning
        # the entire table (we rerun models many times per game).
        if lookback_days and int(lookback_days) > 0:
            conditions.append("m.analyzed_at >= (NOW() - (%s || ' days')::interval)")
            params.append(int(lookback_days))

        # Only show games that have actually started or finished
        conditions.append("e.start_time <= (NOW() + INTERVAL '10 minutes')")

    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Lightweight columns - excludes inputs_json, outputs_json, narrative_json
    _LIGHT_COLS = """m.id, m.event_id, m.user_id, m.analyzed_at, m.model_version,
        m.market_type, m.pick, m.bet_line, m.bet_price, m.book,
        m.mu_market, m.mu_torvik, m.mu_final, m.sigma,
        m.win_prob, m.ev_per_unit, m.confidence_0_100,
        m.outcome, m.close_line, m.close_price,
        m.selection, m.price, m.fair_line, m.edge_points,
        m.open_line, m.open_price, m.clv_points, m.clv_price_delta,
        m.clv_method, m.close_captured_at, m.prediction_key"""

    if recommended_only and dedupe:
        # Dedupe: keep only the latest rec per game+market.
        # Postgres DISTINCT ON keeps first row per group based on ORDER BY.
        query = f"""
        WITH base AS (
            SELECT {_LIGHT_COLS}, e.league as sport, e.home_team, e.away_team, e.start_time
            FROM model_predictions m
            JOIN events e ON m.event_id = e.id
            {where_sql}
            -- Do not exclude recs that were computed close to (or even after) start_time.
            -- Start times can be corrected/shifted and we still want to display the recommendation.
        ), deduped AS (
            SELECT DISTINCT ON (event_id, market_type)
                *
            FROM base
            ORDER BY event_id, market_type, analyzed_at DESC
        )
        SELECT *
        FROM deduped
        ORDER BY analyzed_at DESC
        LIMIT %s
        """
        params2 = list(params) + [limit]
        with get_db_connection() as conn:
            cursor = _exec(conn, query, tuple(params2))
            return [dict(r) for r in cursor.fetchall()]

    # Non-deduped path
    base_query = f"""
    SELECT {_LIGHT_COLS}, e.league as sport, e.home_team, e.away_team, e.start_time
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    {where_sql}
    ORDER BY m.analyzed_at DESC
    LIMIT %s
    """
    params.append(limit)

    with get_db_connection() as conn:
        cursor = _exec(conn, base_query, tuple(params))
        return [dict(r) for r in cursor.fetchall()]


def fetch_bet_detail(bet_id: int, user_id: str = None):
    """Fetch a single bet with ALL columns including raw_text (detail view)."""
    q = "SELECT * FROM bets WHERE id = %s"
    params = [bet_id]
    if user_id:
        q += " AND user_id = %s"
        params.append(user_id)
    with get_db_connection() as conn:
        row = _exec(conn, q, tuple(params)).fetchone()
        return dict(row) if row else None


def fetch_model_prediction_detail(prediction_id: str):
    """Fetch a single model prediction with ALL columns including JSON blobs (detail view)."""
    q = """
    SELECT m.*, e.league as sport, e.home_team, e.away_team, e.start_time
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    WHERE m.id = %s
    """
    with get_db_connection() as conn:
        row = _exec(conn, q, (prediction_id,)).fetchone()
        return dict(row) if row else None


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
    """Upsert daily team metrics to bt_team_metrics_daily.

    Expected payload keys: team_text, date, adj_off, adj_def, adj_tempo
    Optional: torvik_rank, record
    """

    query = """
    INSERT INTO bt_team_metrics_daily (team_text, date, adj_off, adj_def, adj_tempo, torvik_rank, record)
    VALUES (:team_text, :date, :adj_off, :adj_def, :adj_tempo, :torvik_rank, :record)
    ON CONFLICT (team_text, date) DO UPDATE SET
        adj_off = EXCLUDED.adj_off,
        adj_def = EXCLUDED.adj_def,
        adj_tempo = EXCLUDED.adj_tempo,
        torvik_rank = EXCLUDED.torvik_rank,
        record = EXCLUDED.record
    """
    with get_db_connection() as conn:
        # Defensive migrations (prod DB may lag new columns)
        try:
            _exec(conn, "ALTER TABLE bt_team_metrics_daily ADD COLUMN IF NOT EXISTS torvik_rank INTEGER;")
            _exec(conn, "ALTER TABLE bt_team_metrics_daily ADD COLUMN IF NOT EXISTS record TEXT;")
        except Exception:
            pass

        for m in metrics:
            # Ensure optional keys exist for SQL named params
            if 'torvik_rank' not in m:
                m['torvik_rank'] = None
            if 'record' not in m:
                m['record'] = None
            _exec(conn, query, m)
        conn.commit()


def fetch_model_health_daily(date=None, league=None, market_type=None):
    """Retrieves aggregated metrics from model_health_daily."""
    with get_db_connection() as conn:
        q = "SELECT * FROM model_health_daily WHERE 1=1"
        params = {}
        if date:
            q += " AND date = :date"
            params["date"] = str(date)
        if league:
            q += " AND league = :league"
            params["league"] = league
        if market_type:
            q += " AND market_type = :market"
            params["market"] = market_type
        
        cursor = _exec(conn, q, params)
        return [dict(r) for r in cursor.fetchall()]

def store_daily_evaluation(metrics):
    """
    Persists a list of metrics to model_health_daily.
    Input: list of dicts with {date, model_version_id, league, market_type, metric_name, metric_value, sample_size}
    """
    if not metrics:
        return
        
    with get_db_connection() as conn:
        q = """
        INSERT INTO model_health_daily (
            date, model_version_id, league, market_type, 
            metric_name, metric_value, sample_size
        ) VALUES (
            :date, :model_version_id, :league, :market_type, 
            :metric_name, :metric_value, :sample_size
        )
        ON CONFLICT (date, model_version_id, league, market_type, metric_name)
        DO UPDATE SET 
            metric_value = EXCLUDED.metric_value,
            sample_size = EXCLUDED.sample_size
        """
        for m in metrics:
            _exec(conn, q, m)
        conn.commit()


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
        account_id TEXT,
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
    CREATE INDEX IF NOT EXISTS idx_txn_user_provider_account_date ON transactions(user_id, provider, COALESCE(account_id,'Main'), date DESC);
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
        account_id TEXT,
        balance NUMERIC(12,2) NOT NULL,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        source TEXT NOT NULL DEFAULT 'manual',  -- manual|csv|api|scrape
        user_id TEXT,
        note TEXT,
        raw_data JSONB
    );
    CREATE INDEX IF NOT EXISTS idx_balance_snaps_provider_time ON balance_snapshots(provider, captured_at DESC);
    CREATE INDEX IF NOT EXISTS idx_balance_snaps_user_provider_account_time ON balance_snapshots(user_id, provider, account_id, captured_at DESC);
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


def init_ncaam_net_rankings_db():
    """Daily NCAA NET rankings snapshot (NCAA.com).

    Stores team rank + records by location + quadrant records.
    """
    drops = ["DROP TABLE IF EXISTS ncaam_net_rankings_daily CASCADE;"] if _force_reset() else []

    schema = """
    CREATE TABLE IF NOT EXISTS ncaam_net_rankings_daily (
        id BIGSERIAL PRIMARY KEY,
        asof_date TEXT NOT NULL,
        rank INTEGER,
        school TEXT NOT NULL,
        record TEXT,
        conf TEXT,
        road TEXT,
        neutral TEXT,
        home TEXT,
        prev INTEGER,
        quad1 TEXT,
        quad2 TEXT,
        quad3 TEXT,
        quad4 TEXT,
        raw TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(asof_date, school)
    );
    CREATE INDEX IF NOT EXISTS idx_net_school_date ON ncaam_net_rankings_daily(school, asof_date DESC);
    CREATE INDEX IF NOT EXISTS idx_net_rank_date ON ncaam_net_rankings_daily(asof_date, rank);
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

    print("NET rankings table initialized.")


def upsert_ncaam_net_rankings_daily(rows: list[dict]):
    """Upsert daily NET rows."""
    init_ncaam_net_rankings_db()

    q = """
    INSERT INTO ncaam_net_rankings_daily (
        asof_date, rank, school, record, conf, road, neutral, home, prev,
        quad1, quad2, quad3, quad4, raw
    ) VALUES (
        :asof_date, :rank, :school, :record, :conf, :road, :neutral, :home, :prev,
        :quad1, :quad2, :quad3, :quad4, :raw
    )
    ON CONFLICT (asof_date, school) DO UPDATE SET
        rank = EXCLUDED.rank,
        record = EXCLUDED.record,
        conf = EXCLUDED.conf,
        road = EXCLUDED.road,
        neutral = EXCLUDED.neutral,
        home = EXCLUDED.home,
        prev = EXCLUDED.prev,
        quad1 = EXCLUDED.quad1,
        quad2 = EXCLUDED.quad2,
        quad3 = EXCLUDED.quad3,
        quad4 = EXCLUDED.quad4,
        raw = EXCLUDED.raw,
        created_at = NOW()
    """

    # Defensive migration if table existed before
    with get_db_connection() as conn:
        try:
            _exec(conn, "ALTER TABLE ncaam_net_rankings_daily ADD COLUMN IF NOT EXISTS road TEXT;")
            _exec(conn, "ALTER TABLE ncaam_net_rankings_daily ADD COLUMN IF NOT EXISTS neutral TEXT;")
            _exec(conn, "ALTER TABLE ncaam_net_rankings_daily ADD COLUMN IF NOT EXISTS home TEXT;")
            _exec(conn, "ALTER TABLE ncaam_net_rankings_daily ADD COLUMN IF NOT EXISTS quad1 TEXT;")
            _exec(conn, "ALTER TABLE ncaam_net_rankings_daily ADD COLUMN IF NOT EXISTS quad2 TEXT;")
            _exec(conn, "ALTER TABLE ncaam_net_rankings_daily ADD COLUMN IF NOT EXISTS quad3 TEXT;")
            _exec(conn, "ALTER TABLE ncaam_net_rankings_daily ADD COLUMN IF NOT EXISTS quad4 TEXT;")
        except Exception:
            pass

        for r in rows or []:
            _exec(conn, q, r)
        conn.commit()


def fetch_latest_ncaam_net_rankings(asof_date: str | None = None):
    """Fetch latest NET snapshot (optionally for a specific asof_date)."""
    with get_db_connection() as conn:
        if asof_date:
            rows = _exec(conn, """
                SELECT *
                FROM ncaam_net_rankings_daily
                WHERE asof_date = :d
                ORDER BY rank ASC NULLS LAST
            """, {"d": asof_date}).fetchall()
        else:
            drow = _exec(conn, "SELECT MAX(asof_date) AS d FROM ncaam_net_rankings_daily").fetchone()
            d = (dict(drow).get('d') if drow else None)
            if not d:
                return {"asof_date": None, "rows": []}
            rows = _exec(conn, """
                SELECT *
                FROM ncaam_net_rankings_daily
                WHERE asof_date = :d
                ORDER BY rank ASC NULLS LAST
            """, {"d": d}).fetchall()
            asof_date = d

    return {"asof_date": asof_date, "rows": [dict(r) for r in rows]}


def fetch_team_net_row(team_name: str, asof_date: str | None = None):
    """Fetch a single team's NET row (best-effort, but avoids common false matches).

    We do *not* rely purely on the generic TeamMatcher here because NET team names
    include ambiguous substrings (e.g., "Michigan" vs "Michigan St.").
    """

    def _norm(s: str) -> str:
        s = (s or '').lower().strip()
        s = re.sub(r"[\.'()&]", "", s)
        s = re.sub(r"\s+", " ", s)
        # Expand common abbreviations
        s = s.replace(' st ', ' state ')
        if s.endswith(' st'):
            s = s[:-3] + ' state'
        return s.strip()

    want = _norm(team_name)

    with get_db_connection() as conn:
        # Resolve asof_date if not provided
        d = asof_date
        if not d:
            drow = _exec(conn, "SELECT MAX(asof_date) AS d FROM ncaam_net_rankings_daily").fetchone()
            d = (dict(drow).get('d') if drow else None)
        if not d:
            return None

        rows = _exec(conn, """
            SELECT *
            FROM ncaam_net_rankings_daily
            WHERE asof_date = :d
        """, {"d": d}).fetchall()

    best = None
    best_score = -1

    for r in rows:
        rr = dict(r)
        name = rr.get('school') or ''
        cand = _norm(name)

        # Exact match wins
        if cand == want:
            return rr

        # Score by token overlap + containment
        w_tokens = set(want.split())
        c_tokens = set(cand.split())
        overlap = len(w_tokens & c_tokens)
        score = overlap * 10

        if want in cand:
            score += 5
        if cand in want:
            score += 3

        # Penalize short/ambiguous matches
        score += min(len(cand), 40) * 0.01

        if score > best_score:
            best_score = score
            best = rr

    return best


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

def get_job_state(job_name: str) -> dict:
    """Gets persistence state for a job."""
    with get_db_connection() as conn:
        row = _exec(conn, "SELECT state FROM job_state WHERE job_name = :n", {"n": job_name}).fetchone()
        return dict(row['state']) if row and row['state'] else {}

def set_job_state(job_name: str, state: dict):
    """Upserts persistence state for a job."""
    query = """
    INSERT INTO job_state (job_name, state, updated_at)
    VALUES (:n, :s, CURRENT_TIMESTAMP)
    ON CONFLICT (job_name) DO UPDATE SET
        state = EXCLUDED.state,
        updated_at = CURRENT_TIMESTAMP
    """
    with get_db_connection() as conn:
        _exec(conn, query, {"n": job_name, "s": psycopg2.extras.Json(state)})
        conn.commit()

def get_latest_odds_for_diffing(sport_league: str) -> list:
    """
    Fetches the latest odds snapshots for a sport/league to use as a baseline for change detection.
    (Used to replace CSV-based state in fetch_action_odds.py)
    """
    # Note: Action Network IDs are typically 6-7 digit strings in this system.
    # We join with events to filter by league if possible, 
    # but for pure diffing we can just look at recent snapshots by book='actionnetwork'.
    query = """
    SELECT event_id, market_type, side, line_value, price
    FROM (
        SELECT event_id, market_type, side, line_value, price,
               ROW_NUMBER() OVER (PARTITION BY event_id, market_type, side ORDER BY captured_at DESC) as rn
        FROM odds_snapshots
        WHERE book = 'actionnetwork'
          AND captured_at > NOW() - INTERVAL '3 days'
    ) t
    WHERE rn = 1
    """
    with get_db_connection() as conn:
        cursor = _exec(conn, query)
        return [dict(r) for r in cursor.fetchall()]

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
        SELECT id, user_id, account_id, provider, date, date_et, sport, bet_type,
               wager, profit, status, status_raw, description, selection, odds,
               closing_odds, is_live, is_bonus, event_text, created_at
        FROM bets
        WHERE user_id = %s
        ORDER BY COALESCE(date_et::text, date) DESC
        """
        # include raw_text so the UI can infer the matchup/event for display
        params = [user_id]
        if limit:
            query += " LIMIT %s"
            params.append(limit)
        with get_db_connection() as conn:
            # Defensive migration: prod DB may lag new columns.
            try:
                _exec(conn, "ALTER TABLE bets ADD COLUMN IF NOT EXISTS event_text TEXT;")
            except Exception:
                pass
            cursor = _exec(conn, query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]
    else:
        query = """
        SELECT id, user_id, account_id, provider, date, date_et, sport, bet_type,
               wager, profit, status, status_raw, description, selection, odds,
               closing_odds, is_live, is_bonus, event_text, created_at
        FROM bets
        ORDER BY COALESCE(date_et::text, date) DESC
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        with get_db_connection() as conn:
            # Defensive migration: prod DB may lag new columns.
            try:
                _exec(conn, "ALTER TABLE bets ADD COLUMN IF NOT EXISTS event_text TEXT;")
            except Exception:
                pass
            cursor = _exec(conn, query)
            return [dict(r) for r in cursor.fetchall()]

def fetch_latest_balance_snapshots(user_id: str | None = None):
    """Fetch latest balance snapshot per provider, with optional per-account detail.

    Returns a dict keyed by provider:
      {
        "DraftKings": {
          "balance": <total across accounts>,
          "captured_at": <max captured_at>,
          "source": "manual|...",
          "accounts": {
            "Main": {"balance": ..., "captured_at": ..., "source": ...},
            "User2": {...}
          }
        },
        ...
      }

    Backward compatible: callers can still read provider.balance.
    """

    q = """
    SELECT DISTINCT ON (provider, COALESCE(account_id, ''))
           provider,
           COALESCE(account_id, '') AS account_id,
           balance,
           captured_at,
           source
    FROM balance_snapshots
    WHERE (:user_id IS NULL OR user_id = :user_id)
    ORDER BY provider, COALESCE(account_id, ''), captured_at DESC
    """
    out: dict = {}
    try:
        with get_db_connection() as conn:
            # Defensive migration for older DBs
            try:
                _exec(conn, "ALTER TABLE balance_snapshots ADD COLUMN IF NOT EXISTS account_id TEXT;")
            except Exception:
                pass

            rows = _exec(conn, q, {"user_id": user_id}).fetchall()
            for r in rows:
                d = dict(r)
                prov = d.get('provider')
                acc = d.get('account_id') or ''
                if not prov:
                    continue

                snap = {
                    "balance": float(d.get('balance') or 0),
                    "captured_at": d.get('captured_at'),
                    "source": d.get('source')
                }

                if prov not in out:
                    out[prov] = {"balance": 0.0, "captured_at": None, "source": None, "accounts": {}}

                key = acc if acc else 'Main'
                out[prov]["accounts"][key] = snap

            # Aggregate totals
            for prov, obj in out.items():
                accs = obj.get('accounts') or {}
                obj['balance'] = float(sum(float(v.get('balance') or 0) for v in accs.values()))
                # captured_at: max over accounts
                try:
                    caps = [v.get('captured_at') for v in accs.values() if v.get('captured_at')]
                    obj['captured_at'] = max(caps) if caps else None
                except Exception:
                    obj['captured_at'] = None
                # source: use the source of the newest snapshot if possible
                try:
                    newest = None
                    for k, v in accs.items():
                        if not v.get('captured_at'):
                            continue
                        if newest is None or v['captured_at'] > newest['captured_at']:
                            newest = v
                    obj['source'] = newest.get('source') if newest else None
                except Exception:
                    obj['source'] = None

    except Exception as e:
        print(f"[DB] fetch_latest_balance_snapshots error: {e}")
    return out


def insert_balance_snapshot(snapshot: dict) -> bool:
    """Insert a balance snapshot row."""
    q = """
    INSERT INTO balance_snapshots (provider, account_id, balance, captured_at, source, user_id, note, raw_data)
    VALUES (:provider, :account_id, :balance, COALESCE(:captured_at, NOW()), COALESCE(:source, 'manual'), :user_id, :note, :raw_data)
    """
    doc = {
        "provider": snapshot.get("provider"),
        "account_id": snapshot.get("account_id"),
        "balance": snapshot.get("balance"),
        "captured_at": snapshot.get("captured_at"),
        "source": snapshot.get("source") or 'manual',
        "user_id": snapshot.get("user_id"),
        "note": snapshot.get("note"),
        "raw_data": psycopg2.extras.Json(snapshot.get("raw_data")) if snapshot.get("raw_data") is not None else None,
    }
    try:
        with get_db_connection() as conn:
            # Defensive migration for older DBs
            try:
                _exec(conn, "ALTER TABLE balance_snapshots ADD COLUMN IF NOT EXISTS account_id TEXT;")
            except Exception:
                pass
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



def update_bet_fields(bet_id: int, fields: dict, user_id: str | None = None, update_note: str | None = None) -> bool:
    """Update editable bet fields (manual corrections).

    Allowed fields:
      provider, date, sport, bet_type, wager, odds, profit, status, description, selection

    Notes:
    - Persists directly to DB so it shows up in history/analytics.
    - Scoped to user_id when provided.
    """
    allowed = {
        'provider', 'account_id', 'date', 'sport', 'bet_type', 'wager', 'odds', 'profit', 'status',
        'description', 'selection', 'event_text'
    }

    # Always write audit fields on a successful update
    # (columns added via init_bets_db migrations)
    audit_note = None
    try:
        audit_note = (update_note or '').strip() or None
    except Exception:
        audit_note = None

    if not fields or not isinstance(fields, dict):
        return False

    sets = []
    params = []

    def norm_provider(x: str) -> str:
        p = (x or '').strip()
        if p.upper() == 'DK':
            return 'DraftKings'
        if p.upper() in ('FD', 'FANDUEL'):
            return 'FanDuel'
        return p

    # If user changes selection/description and doesn't explicitly set event_text,
    # recompute it from the updated fields + existing raw_text (so Event column updates).
    needs_event_recalc = (
        ('event_text' not in fields)
        and any(k in fields for k in ('selection', 'description'))
    )

    existing = None
    if needs_event_recalc:
        try:
            with get_db_connection() as conn:
                existing = _exec(
                    conn,
                    "SELECT raw_text, description, selection FROM bets WHERE id=%s AND (%s IS NULL OR user_id=%s)",
                    (int(bet_id), user_id, user_id),
                ).fetchone()
        except Exception:
            existing = None

    def _extract_event_text_from(raw_text: str, description: str, selection: str) -> str | None:
        try:
            def clean_side(x: str) -> str:
                x = (x or '').strip()
                x = re.split(r"\s+[+\---]\d+(?:\.\d+)?\b", x, maxsplit=1)[0]
                x = re.split(r"\s+\b(over|under)\b\s*\d+(?:\.\d+)?\b", x, flags=re.IGNORECASE, maxsplit=1)[0]
                x = re.split(r"\s+\bml\b", x, flags=re.IGNORECASE, maxsplit=1)[0]
                x = re.split(r"\s+\|", x, maxsplit=1)[0]
                x = re.sub(r"\s+", " ", x).strip()
                x = re.sub(r"\b([A-Za-z]{3,})\s+\1\b", r"\1", x, flags=re.IGNORECASE)
                return x.strip()

            sources = [str(raw_text or ''), str(description or ''), str(selection or '')]
            for src in sources:
                if not src:
                    continue
                for ln in str(src).splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    if ('@' in ln) or re.search(r"\b(vs\.?|versus)\b", ln, re.IGNORECASE):
                        m = re.search(r"(.+?)\s*(?:@|vs\.?|versus)\s*(.+)$", ln, flags=re.IGNORECASE)
                        if m:
                            a = clean_side(m.group(1))
                            b = clean_side(m.group(2))
                            if a and b:
                                return f"{a} @ {b}"[:160]

            s = "\n".join(sources)
            s = re.sub(r"\s+", " ", s).strip()
            m = re.search(r"(.+?)\s*(?:@|vs\.?|versus)\s*(.+?)(?:\s*\||\s*$)", s, flags=re.IGNORECASE)
            if not m:
                return None
            a = clean_side(m.group(1))
            b = clean_side(m.group(2))
            if a and b:
                return f"{a} @ {b}"[:160]
        except Exception:
            return None
        return None

    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == 'provider':
            v = norm_provider(str(v))
        if k == 'status':
            v = str(v or '').upper()
            if v not in ('WON', 'LOST', 'PUSH', 'PENDING'):
                continue
        if k in ('wager', 'profit'):
            try:
                v = float(v)
            except Exception:
                continue
        if k == 'odds':
            if v is None or v == '':
                v = None
            else:
                try:
                    v = int(v)
                except Exception:
                    continue
        if k == 'date':
            # store as YYYY-MM-DD string
            v = str(v or '').strip()
            if not v:
                continue
        sets.append(f"{k}=%s")
        params.append(v)

    if needs_event_recalc and existing:
        try:
            raw_text = existing.get('raw_text') if hasattr(existing, 'get') else existing[0]
            cur_desc = existing.get('description') if hasattr(existing, 'get') else existing[1]
            cur_sel = existing.get('selection') if hasattr(existing, 'get') else existing[2]
            new_desc = fields.get('description', cur_desc)
            new_sel = fields.get('selection', cur_sel)
            ev = _extract_event_text_from(raw_text, new_desc, new_sel)
            if ev:
                sets.append("event_text=%s")
                params.append(ev)
        except Exception:
            pass

    if not sets:
        return False

    # Add audit columns
    sets.append("updated_at=NOW()")
    sets.append("updated_by=%s")
    params.append(user_id)
    sets.append("update_note=%s")
    params.append(audit_note)

    q = f"""
    UPDATE bets
    SET {', '.join(sets)}
    WHERE id=%s AND (%s IS NULL OR user_id=%s)
    """
    params.extend([int(bet_id), user_id, user_id])

    def _ensure_audit_cols(conn):
        # These are safe to run repeatedly.
        try:
            _exec(conn, "ALTER TABLE bets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;")
            _exec(conn, "ALTER TABLE bets ADD COLUMN IF NOT EXISTS updated_by TEXT;")
            _exec(conn, "ALTER TABLE bets ADD COLUMN IF NOT EXISTS update_note TEXT;")
        except Exception:
            pass

    try:
        with get_db_connection() as conn:
            _ensure_audit_cols(conn)
            cur = _exec(conn, q, tuple(params))
            conn.commit()
            success = bool(cur.rowcount and cur.rowcount > 0)

        if success:
            _sync_transaction_for_bet(bet_id)

        return success
    except Exception as e:
        print(f"[DB] update_bet_fields error: {e}")
        return False


def delete_bet(bet_id: int, user_id: str | None = None) -> bool:
    """Delete a bet row (scoped to user_id when provided).

    Note: bets can be referenced by bet_legs and settlement_events with NO ACTION.
    We must delete dependents first.
    """
    q_bet = "DELETE FROM bets WHERE id=%s AND (%s IS NULL OR user_id=%s)"
    q_txn = "DELETE FROM transactions WHERE txn_id=%s AND (%s IS NULL OR user_id=%s)"
    # bet_legs / settlement_events do NOT have user_id columns; scope is enforced by deleting the bet row itself.
    q_legs = "DELETE FROM bet_legs WHERE bet_id=%s"
    q_sett = "DELETE FROM settlement_events WHERE bet_id=%s"
    try:
        with get_db_connection() as conn:
            # Delete dependents first to satisfy FK constraints
            _exec(conn, q_legs, (int(bet_id),))
            _exec(conn, q_sett, (int(bet_id),))
            _exec(conn, q_txn, (f"bet_{bet_id}", user_id, user_id))
            cur = _exec(conn, q_bet, (int(bet_id), user_id, user_id))
            conn.commit()
            return bool(cur.rowcount and cur.rowcount > 0)
    except Exception as e:
        print(f"[DB] delete_bet error: {e}")
        return False

def bulk_delete_bets(bet_ids: list[int], user_id: str | None = None) -> int:
    """Delete multiple bets and their associated transactions + dependent rows."""
    q_bet = "DELETE FROM bets WHERE id=ANY(%s) AND (%s IS NULL OR user_id=%s)"
    q_txn = "DELETE FROM transactions WHERE txn_id=ANY(%s) AND (%s IS NULL OR user_id=%s)"
    # bet_legs / settlement_events do NOT have user_id columns; scope is enforced by deleting bets.
    q_legs = "DELETE FROM bet_legs WHERE bet_id=ANY(%s)"
    q_sett = "DELETE FROM settlement_events WHERE bet_id=ANY(%s)"
    txn_ids = [f"bet_{bid}" for bid in bet_ids]
    try:
        with get_db_connection() as conn:
            _exec(conn, q_legs, (list(bet_ids),))
            _exec(conn, q_sett, (list(bet_ids),))
            _exec(conn, q_txn, (txn_ids, user_id, user_id))
            cur = _exec(conn, q_bet, (list(bet_ids), user_id, user_id))
            conn.commit()
            return cur.rowcount
    except Exception as e:
        print(f"[DB] bulk_delete_bets error: {e}")
        return 0


def insert_bet(bet_data: dict):
    """
    Inserts a single bet into the bets table with idempotency.
    """
    query = """
    INSERT INTO bets (user_id, account_id, provider, date, sport, bet_type,
                      wager, profit, status, description, selection, odds,
                      closing_odds, is_live, is_bonus, raw_text, event_text)
    VALUES (:user_id, :account_id, :provider, :date, :sport, :bet_type,
            :wager, :profit, :status, :description, :selection, :odds,
            :closing_odds, :is_live, :is_bonus, :raw_text, :event_text)
    ON CONFLICT (user_id, provider, description, date, wager) DO UPDATE SET
        profit = EXCLUDED.profit,
        status = EXCLUDED.status,
        closing_odds = EXCLUDED.closing_odds
    """
    # Ensure all required fields
    defaults = {
        'account_id': None, 'selection': None, 'odds': None,
        'closing_odds': None, 'is_live': False, 'is_bonus': False, 'raw_text': None, 'event_text': None
    }
    for k, v in defaults.items():
        if k not in bet_data:
            bet_data[k] = v

    # Fill event_text if missing
    if not bet_data.get('event_text'):
        try:
            s = "\n".join([
                str(bet_data.get('raw_text') or ''),
                str(bet_data.get('description') or ''),
                str(bet_data.get('selection') or ''),
            ])
            s = re.sub(r"\s+", " ", s).strip()
            m = re.search(r"(.+?)\s*(?:@|vs\.?|versus)\s*(.+?)(?:\s*\||\s*$)", s, flags=re.IGNORECASE)
            if m:
                a = (m.group(1) or '').strip()
                b = (m.group(2) or '').strip()
                if a and b:
                    bet_data['event_text'] = f"{a} @ {b}"[:160]
        except Exception:
            pass

    with get_db_connection() as conn:
        _exec(conn, query, bet_data)
        conn.commit()

def insert_transaction(txn: dict) -> bool:
    """
    Insert a single transaction with idempotency via (provider, txn_id).
    Maps incoming fields from parsers to database schema.
    Returns True if inserted/updated, False on error.

    Note: `transactions.raw_data` is TEXT in our schema, so we JSON-serialize
    dict/list payloads for safety.
    """
    query = """
    INSERT INTO transactions (provider, account_id, txn_id, date, type, description,
                              amount, balance, user_id, raw_data)
    VALUES (:provider, :account_id, :txn_id, :date, :type, :description,
            :amount, :balance, :user_id, :raw_data)
    ON CONFLICT (provider, txn_id) DO UPDATE SET
        amount = EXCLUDED.amount,
        balance = EXCLUDED.balance,
        type = EXCLUDED.type,
        description = EXCLUDED.description,
        raw_data = COALESCE(EXCLUDED.raw_data, transactions.raw_data)
    """

    import json

    def _raw_to_text(x):
        if x is None:
            return None
        if isinstance(x, (dict, list)):
            try:
                return json.dumps(x)
            except Exception:
                return str(x)
        return str(x)

    # Map incoming fields from parsers to schema
    doc = {
        'provider': txn.get('provider') or txn.get('sportsbook'),
        'account_id': txn.get('account_id'),
        'txn_id': txn.get('id') or txn.get('txn_id'),
        'date': txn.get('date') or txn.get('txn_date'),
        'type': txn.get('type') or txn.get('txn_type'),
        'description': txn.get('description'),
        'amount': txn.get('amount'),
        'balance': txn.get('balance'),
        'user_id': txn.get('user_id') or '00000000-0000-0000-0000-000000000000',
        'raw_data': _raw_to_text(txn.get('raw_data'))
    }

    try:
        with get_db_connection() as conn:
            # Defensive migration for older DBs
            try:
                _exec(conn, "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS account_id TEXT;")
            except Exception:
                pass
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

def get_team_efficiency_by_name(team_name: str) -> dict:
    """
    Fetch latest team efficiency metrics (AdjO, AdjD, etc) from bt_team_metrics.
    Returns empty dict if not found.
    """
    # Use fuzzy match or strict? Strict for now, assuming canonical names are used or handled.
    # Actually most reliable is to query by LIKE or exact.
    query = """
    SELECT * FROM bt_team_metrics
    WHERE team_name = %s
    ORDER BY date DESC
    LIMIT 1
    """
    try:
        with get_db_connection() as conn:
            row = _exec(conn, query, (team_name,)).fetchone()
            if row:
                return dict(row)
    except Exception as e:
        print(f"[DB] get_team_efficiency_by_name error: {e}")

    return {}


# --- Advanced Situational Signals Tables ---

def init_team_game_logs_table():
    """Create team_game_logs table for shooting regression analysis."""
    schema = """
    CREATE TABLE IF NOT EXISTS team_game_logs (
        id SERIAL PRIMARY KEY,
        team_text TEXT NOT NULL,
        game_date DATE NOT NULL,
        opponent TEXT,
        points INTEGER,
        three_p_made INTEGER,
        three_p_attempted INTEGER,
        three_p_pct REAL,
        fouls INTEGER,
        opponent_rank INTEGER,
        is_home BOOLEAN,
        margin INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(team_text, game_date, opponent)
    );
    CREATE INDEX IF NOT EXISTS idx_team_game_logs_team ON team_game_logs(team_text);
    CREATE INDEX IF NOT EXISTS idx_team_game_logs_date ON team_game_logs(game_date DESC);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
    print("team_game_logs table initialized.")


def init_referee_assignments_table():
    """Create referee_assignments table for officiating signal."""
    schema = """
    CREATE TABLE IF NOT EXISTS referee_assignments (
        id SERIAL PRIMARY KEY,
        event_id TEXT NOT NULL,
        referee_1 TEXT,
        referee_2 TEXT,
        referee_3 TEXT,
        crew_avg_fouls REAL,
        source TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(event_id)
    );
    CREATE INDEX IF NOT EXISTS idx_ref_event ON referee_assignments(event_id);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
    print("referee_assignments table initialized.")


def get_team_recent_shooting(team_name: str, num_games: int = 3) -> dict:
    """
    Get a team's recent 3PT shooting vs their season average.
    Returns: {recent_3p_pct, season_3p_pct, delta}
    """
    query = """
    WITH recent AS (
        SELECT AVG(three_p_pct) as recent_avg
        FROM (
            SELECT three_p_pct FROM team_game_logs
            WHERE team_text ILIKE %s
            ORDER BY game_date DESC LIMIT %s
        ) sub
    ),
    season AS (
        SELECT AVG(three_p_pct) as season_avg
        FROM team_game_logs
        WHERE team_text ILIKE %s
    )
    SELECT recent.recent_avg, season.season_avg
    FROM recent, season
    """
    with get_db_connection() as conn:
        result = _exec(conn, query, (f"%{team_name}%", num_games, f"%{team_name}%")).fetchone()
        if result and result[0] and result[1]:
            return {
                "recent_3p_pct": float(result[0]),
                "season_3p_pct": float(result[1]),
                "delta": float(result[0]) - float(result[1])
            }
    return {"recent_3p_pct": None, "season_3p_pct": None, "delta": 0.0}


def get_team_last_game(team_name: str) -> dict:
    """Get result of team's most recent game for letdown/momentum analysis."""
    query = """
    SELECT game_date, opponent, margin, is_home, opponent_rank
    FROM team_game_logs
    WHERE team_text ILIKE %s
    ORDER BY game_date DESC LIMIT 1
    """
    with get_db_connection() as conn:
        result = _exec(conn, query, (f"%{team_name}%",)).fetchone()
        if result:
            return dict(result)
    return {}


def upsert_referee_assignment(event_id: str, referee_1: str = None, referee_2: str = None, referee_3: str = None, crew_avg_fouls: float = None, source: str = 'manual') -> None:
    """Insert/update referee crew for an event (manual or automated)."""
    init_referee_assignments_table()
    sql = """
    INSERT INTO referee_assignments(event_id, referee_1, referee_2, referee_3, crew_avg_fouls, source, fetched_at)
    VALUES (%s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (event_id) DO UPDATE SET
      referee_1=EXCLUDED.referee_1,
      referee_2=EXCLUDED.referee_2,
      referee_3=EXCLUDED.referee_3,
      crew_avg_fouls=COALESCE(EXCLUDED.crew_avg_fouls, referee_assignments.crew_avg_fouls),
      source=EXCLUDED.source,
      fetched_at=NOW();
    """
    with get_admin_db_connection() as conn:
        _exec(conn, sql, (event_id, referee_1, referee_2, referee_3, crew_avg_fouls, source))
        conn.commit()


def get_referee_assignment(event_id: str) -> dict:
    """Get referee crew and their foul rate for an event."""
    query = """
    SELECT referee_1, referee_2, referee_3, crew_avg_fouls
    FROM referee_assignments
    WHERE event_id = %s
    """
    with get_db_connection() as conn:
        result = _exec(conn, query, (event_id,)).fetchone()
        if result:
            return dict(result)
    return {}
