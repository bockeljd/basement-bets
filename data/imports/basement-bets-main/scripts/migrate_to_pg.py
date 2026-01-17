import sys
import os
import sqlite3
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.database import init_db, init_model_history, init_transactions_tab, init_player_stats_db

def migrate():
    # Load environment variables (try .env.development.local first for Vercel pulled vars)
    load_dotenv('.env.development.local')
    load_dotenv('.env') # Fallback
    
    pg_url = os.getenv('DATABASE_URL')
    if not pg_url:
        print("Error: DATABASE_URL not set. Please set it to your Postgres connection string.")
        return

    sqlite_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'bets.db')
    
    print(f"Migrating from {sqlite_path} to Postgres...")
    
    # 1. Initialize Postgres Tables
    print("Initializing Postgres schema...")
    # These functions rely on DATABASE_URL being set
    init_db()
    init_model_history()
    init_transactions_tab()
    init_player_stats_db()
    
    # 2. Connect to both
    sq_conn = sqlite3.connect(sqlite_path)
    sq_conn.row_factory = sqlite3.Row
    
    pg_conn = psycopg2.connect(pg_url)
    
    try:
        # 3. Migrate Bets
        print("Migrating 'bets' table...")
        bets = sq_conn.execute("SELECT * FROM bets").fetchall()
        
        insert_bets_query = """
        INSERT INTO bets 
        (provider, date, sport, bet_type, wager, profit, status, description, selection, odds, closing_odds, is_live, is_bonus, raw_text, created_at)
        VALUES %s
        ON CONFLICT DO NOTHING
        """
        
        bets_data = []
        for b in bets:
            bets_data.append((
                b['provider'], b['date'], b['sport'], b['bet_type'], b['wager'], b['profit'], 
                b['status'], b['description'], b['selection'], b['odds'], b['closing_odds'], 
                bool(b['is_live']), bool(b['is_bonus']), b['raw_text'], b['created_at']
            ))
            
        if bets_data:
            with pg_conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, insert_bets_query, bets_data)
            print(f"  -> Migrated {len(bets_data)} bets.")
            
        # 4. Migrate Transactions
        print("Migrating 'transactions' table...")
        txns = sq_conn.execute("SELECT * FROM transactions").fetchall()
        
        insert_txn_query = """
        INSERT INTO transactions
        (txn_id, provider, date, type, description, amount, balance, raw_data, created_at)
        VALUES %s
        ON CONFLICT DO NOTHING
        """
        
        txn_data = []
        for t in txns:
            txn_data.append((
                t['txn_id'], t['provider'], t['date'], t['type'], t['description'], 
                t['amount'], t['balance'], t['raw_data'], t['created_at']
            ))
            
        if txn_data:
            with pg_conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, insert_txn_query, txn_data)
            print(f"  -> Migrated {len(txn_data)} transactions.")

        # 5. Migrate Model History
        print("Migrating 'model_predictions' table...")
        preds = sq_conn.execute("SELECT * FROM model_predictions").fetchall()
        
        if preds:
            insert_pred_query = """
            INSERT INTO model_predictions
            (game_id, sport, date, matchup, bet_on, market, market_line, fair_line, edge, is_actionable, result, created_at)
            VALUES %s
            ON CONFLICT DO NOTHING
            """
            
            pred_data = []
            for p in preds:
                pred_data.append((
                    p['game_id'], p['sport'], p['date'], p['matchup'], p['bet_on'], p['market'],
                    p['market_line'], p['fair_line'], p['edge'], bool(p['is_actionable']), p['result'], p['created_at']
                ))
                
            with pg_conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, insert_pred_query, pred_data)
            print(f"  -> Migrated {len(pred_data)} predictions.")
            
        pg_conn.commit()
        print("\nMigration Complete Successfully!")
        
    except Exception as e:
        print(f"Migration Failed: {e}")
        pg_conn.rollback()
    finally:
        sq_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    migrate()
