import sqlite3
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from urllib.parse import urlparse

# Detect Vercel Environment
IS_VERCEL = os.environ.get("VERCEL") == "1"

# Default to SQLite if no DATABASE_URL is set
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'bets.db')

def get_db_type():
    if IS_VERCEL or os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL'):
        return 'postgres'
    return 'sqlite'

@contextmanager
def get_db_connection():
    if IS_VERCEL:
        # PRODUCTION: Use Vercel Postgres (POSTGRES_URL) or Neon (DATABASE_URL)
        db_url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
        
        if not db_url:
            # Fatal Error: No DB String
            print("[CRITICAL] POSTGRES_URL and DATABASE_URL are missing in Vercel Environment.")
            print("[CRITICAL] Ensure you have added the Neon/Postgres Integration.")
            raise RuntimeError("CRITICAL: Database connection string not found.")

        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.DictCursor)
        try:
            yield conn
        finally:
            conn.close()
    elif os.environ.get('DATABASE_URL'):
        # LOCAL POSTGRES (e.g. for migration testing)
        conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=psycopg2.extras.DictCursor)
        try:
            yield conn
        finally:
            conn.close()
    else:
        # LOCAL SQLITE
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
            sql = re.sub(r'(?<!:):(\w+)', r'%(\1)s', sql)
            
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
            is_live BOOLEAN DEFAULT 0,
            is_bonus BOOLEAN DEFAULT 0,
            raw_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider, description, date, wager)
        );
        """
    else:
        # Postgres Schema
        schema = """
        CREATE TABLE IF NOT EXISTS bets (
            id SERIAL PRIMARY KEY,
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
            UNIQUE(provider, description, date, wager)
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
    # Parameterized query with named params is tricky cross-db if not standard.
    # We will use the unified _exec to handle translation logic.
    query = """
    INSERT OR IGNORE INTO model_predictions 
    (game_id, sport, date, matchup, bet_on, market, market_line, fair_line, edge, is_actionable)
    VALUES (:game_id, :sport, :start_time, :game, :bet_on, :market, :market_line, :fair_line, :edge, :is_actionable)
    """
    with get_db_connection() as conn:
        _exec(conn, query, pred)
        conn.commit()

def fetch_model_history():
    query = "SELECT * FROM model_predictions ORDER BY created_at DESC"
    with get_db_connection() as conn:
        cursor = _exec(conn, query)
        return [dict(row) for row in cursor.fetchall()]

def update_model_prediction_result(prediction_id: int, result: str):
    query = "UPDATE model_predictions SET result = ? WHERE id = ?"
    with get_db_connection() as conn:
        _exec(conn, query, (result, prediction_id))
        conn.commit()

def init_transactions_tab():
    db_type = get_db_type()
    if db_type == 'sqlite':
        schema = """
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
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
    (provider, date, sport, bet_type, wager, profit, status, description, selection, odds, is_live, is_bonus, raw_text)
    VALUES (:provider, :date, :sport, :bet_type, :wager, :profit, :status, :description, :selection, :odds, :is_live, :is_bonus, :raw_text)
    """
    with get_db_connection() as conn:
        _exec(conn, query, bet_data)
        conn.commit()

def insert_transaction(txn_data: dict):
    query = """
    INSERT OR IGNORE INTO transactions
    (txn_id, provider, date, type, description, amount, balance, raw_data)
    VALUES (:id, :provider, :date, :type, :description, :amount, :balance, :raw_data)
    """
    with get_db_connection() as conn:
        _exec(conn, query, txn_data)
        conn.commit()

def fetch_all_bets():
    query = "SELECT * FROM bets ORDER BY date DESC"
    with get_db_connection() as conn:
        cursor = _exec(conn, query)
        return [dict(row) for row in cursor.fetchall()]

def fetch_latest_ledger_info():
    query = """
    SELECT provider, balance, date 
    FROM transactions 
    WHERE date = (SELECT MAX(date) FROM transactions t2 WHERE t2.provider = transactions.provider)
    """
    # Note: This subquery is standard SQL, should work on both.
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
        # SQLite supports executemany.
        # Postgres executemany with named params works via psycopg2 usually.
        # But our _exec wrapper handles single query string translation.
        # For bulk insert, we should ideally use execute_values or similar for PG speed, 
        # but for now reusing loop or executemany checking db type.
        
        is_pg = hasattr(conn, 'cursor_factory')
        if is_pg:
            # Need to translate query ONCE
            query = query.replace("INSERT OR IGNORE", "INSERT").replace("VALUES", "VALUES") + " ON CONFLICT DO NOTHING"
            import re
            query = re.sub(r':(\w+)', r'%(\1)s', query)
            
            with conn.cursor() as cur:
                cur.executemany(query, stats)
        else:
            conn.executemany(query, stats)
            
        conn.commit()
    print(f"Inserted {len(stats)} player stats rows.")
