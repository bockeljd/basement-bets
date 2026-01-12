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

def fetch_all_bets():
    query = "SELECT * FROM bets ORDER BY date DESC"
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query).fetchall()]
