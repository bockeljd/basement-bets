import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'bets.db')

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    schema = """
    DROP TABLE IF EXISTS bets;
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
    with get_db_connection() as conn:
        conn.executescript(schema)
        conn.commit()
    print(f"Database initialized (and reset) at {DB_PATH}")

def add_closing_odds_column():
    """Migration to add closing_odds column to existing bets table."""
    try:
        with get_db_connection() as conn:
            conn.execute("ALTER TABLE bets ADD COLUMN closing_odds INTEGER")
            conn.commit()
        print("Added closing_odds column.")
    except Exception as e:
        print(f"Column closing_odds likely exists: {e}")

def update_closing_odds(bet_id: int, closing_odds: int):
    query = "UPDATE bets SET closing_odds = ? WHERE id = ?"
    with get_db_connection() as conn:
        conn.execute(query, (closing_odds, bet_id))
        conn.commit()

def init_model_history():
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
    with get_db_connection() as conn:
        conn.executescript(schema)
        conn.commit()
    print("Model predictions table initialized.")

def insert_model_prediction(pred: dict):
    query = """
    INSERT OR IGNORE INTO model_predictions 
    (game_id, sport, date, matchup, bet_on, market, market_line, fair_line, edge, is_actionable)
    VALUES (:game_id, :sport, :start_time, :game, :bet_on, :market, :market_line, :fair_line, :edge, :is_actionable)
    """
    # Map 'game' -> matchup, 'start_time' -> date if needed
    # We'll handle key mapping in the caller or here.
    # simpler to expect dict keys to match param names, but our model output keys differ slightly.
    # Let's adjust query to match model output keys + extras.
    
    with get_db_connection() as conn:
        conn.execute(query, pred)
        conn.commit()

def fetch_model_history():
    query = "SELECT * FROM model_predictions ORDER BY created_at DESC"
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query).fetchall()]

def update_model_prediction_result(prediction_id: int, result: str):
    query = "UPDATE model_predictions SET result = ? WHERE id = ?"
    with get_db_connection() as conn:
        conn.execute(query, (result, prediction_id))
        conn.commit()
    print(f"Updated prediction {prediction_id} to result: {result}")

def init_transactions_tab():
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
        conn.executescript(schema)
        conn.commit()
    print("Transactions table initialized.")

def insert_bet(bet_data: dict):
    """
    Inserts a single bet into the database.
    Ignores duplicates based on the UNIQUE constraint.
    """
    query = """
    INSERT OR IGNORE INTO bets 
    (provider, date, sport, bet_type, wager, profit, status, description, selection, odds, is_live, is_bonus, raw_text)
    VALUES (:provider, :date, :sport, :bet_type, :wager, :profit, :status, :description, :selection, :odds, :is_live, :is_bonus, :raw_text)
    """
    with get_db_connection() as conn:
        conn.execute(query, bet_data)
        conn.commit()

def insert_transaction(txn_data: dict):
    query = """
    INSERT OR IGNORE INTO transactions
    (txn_id, provider, date, type, description, amount, balance, raw_data)
    VALUES (:id, :provider, :date, :type, :description, :amount, :balance, :raw_data)
    """
    with get_db_connection() as conn:
        conn.execute(query, txn_data)
        conn.commit()

def fetch_all_bets():
    query = "SELECT * FROM bets ORDER BY date DESC"
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query).fetchall()]

def fetch_latest_ledger_info():
    """Returns the most recent balance and date for each provider from the transactions table."""
    query = """
    SELECT provider, balance, date 
    FROM transactions 
    WHERE date = (SELECT MAX(date) FROM transactions t2 WHERE t2.provider = transactions.provider)
    GROUP BY provider
    """
    with get_db_connection() as conn:
        return {row['provider']: {'balance': row['balance'], 'date': row['date']} for row in conn.execute(query).fetchall()}

def init_player_stats_db():
    schema = """
    CREATE TABLE IF NOT EXISTS player_stats_ncaam (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id TEXT NOT NULL,
        name TEXT NOT NULL,
        team TEXT NOT NULL,
        date TEXT, -- Snapshot date (YYYY-MM-DD or YYYYMMDD)
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
        conn.executescript(schema)
        conn.commit()
    print("Player stats (NCAAM) table initialized.")

def insert_player_stats(stats: list):
    """
    Bulk insert player stats.
    stats: List of dicts matching schema cols.
    """
    query = """
    INSERT OR IGNORE INTO player_stats_ncaam
    (player_id, name, team, date, game_gp, mpg, ortg, usg, efg, ts_pct, orb_pct, drb_pct, ast_pct, to_pct, blk_pct, stl_pct, ftr, pfr, three_p_pct, two_p_pct)
    VALUES 
    (:player_id, :name, :team, :date, :games, :mpg, :ortg, :usg, :efg, :ts_pct, :orb_pct, :drb_pct, :ast_pct, :to_pct, :blk_pct, :stl_pct, :ftr, :pfr, :three_p_pct, :two_p_pct)
    """
    with get_db_connection() as conn:
        conn.executemany(query, stats)
        conn.commit()
    print(f"Inserted {len(stats)} player stats rows.")
