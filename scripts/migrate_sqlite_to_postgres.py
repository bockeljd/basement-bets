
import sqlite3
import psycopg2
import psycopg2.extras
import os
import sys

# Add project root
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.config import settings

SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'bets.db')

def get_postgres_conn():
    # Prefer Unpooled for migration/bulk inserts
    dsn = settings.DATABASE_URL_UNPOOLED or settings.DATABASE_URL
    if not dsn:
        print("[Error] No Postgres URL found (DATABASE_URL_UNPOOLED or DATABASE_URL).")
        sys.exit(1)
    return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.DictCursor)

def migrate_table(pg_conn, sqlite_conn, table_name, conflict_key="id"):
    print(f"\n--- Migrating {table_name} ---")
    
    # 1. Check if table exists in SQLite
    try:
        sqlite_cursor = sqlite_conn.execute(f"SELECT count(*) FROM {table_name}")
        count = sqlite_cursor.fetchone()[0]
        if count == 0:
            print(f"[Skip] {table_name} is empty in SQLite.")
            return
    except sqlite3.OperationalError:
        print(f"[Skip] {table_name} not found in SQLite.")
        return

    # 2. Get Columns from Postgres
    try:
        with pg_conn.cursor() as pg_cur:
            pg_cur.execute(f"SELECT * FROM {table_name} LIMIT 0")
            pg_cols = [desc[0] for desc in pg_cur.description]
    except Exception as e:
        print(f"[Skip] {table_name} not found in Postgres or error: {e}")
        pg_conn.rollback()
        return

    # 3. Get Columns from SQLite
    try:
        # We need actual columns
        sqlite_cursor = sqlite_conn.execute(f"PRAGMA table_info({table_name})")
        sqlite_cols_info = sqlite_cursor.fetchall()
        sqlite_cols = [c['name'] for c in sqlite_cols_info] # sqlite3.Row access
    except Exception:
        print(f"[Error] Could not inspect {table_name} in SQLite.")
        return

    # 4. Intersect Columns
    common_cols = [c for c in sqlite_cols if c in pg_cols]
    if not common_cols:
        print(f"[Skip] No common columns for {table_name}.")
        return
        
    print(f"Migrating {count} rows. Columns: {len(common_cols)}/{len(pg_cols)}")
    
    # 5. Fetch and Insert Batch
    # Batch size
    BATCH_SIZE = 1000
    total_migrated = 0
    
    sqlite_cursor = sqlite_conn.execute(f"SELECT {','.join(common_cols)} FROM {table_name}")
    
    cols_placeholder = ", ".join(common_cols)
    vals_placeholder = ", ".join(["%s"] * len(common_cols))
    
    insert_sql = f"""
        INSERT INTO {table_name} ({cols_placeholder})
        VALUES ({vals_placeholder})
        ON CONFLICT ({conflict_key}) DO NOTHING
    """
    
    while True:
        rows = sqlite_cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break
            
        data_batch = []
        import uuid
        
        for row in rows:
            # Convert row to list for mutation
            vals = list(row[c] for c in common_cols)
            
            # 1. Handle UUID Mapping for 'user_id' or 'account_id' in bets
            if table_name == 'bets':
                try:
                    # user_id
                    if 'user_id' in common_cols:
                        uid_idx = common_cols.index('user_id')
                        raw_uid = vals[uid_idx]
                        if raw_uid and not _is_uuid(raw_uid):
                            # Deterministic hash to UUID
                            vals[uid_idx] = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_uid)))
                            
                    # account_id
                    if 'account_id' in common_cols:
                        aid_idx = common_cols.index('account_id')
                        raw_aid = vals[aid_idx]
                        if raw_aid and not _is_uuid(raw_aid):
                            vals[aid_idx] = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_aid)))
                except Exception as e:
                     print(f"[Warn] UUID conversion error: {e}")

            # 2. Handle Boolean integer conversion (SQLite 0/1 -> PG Bool)
            bool_cols = ['is_live', 'is_bonus', 'is_parlay', 'final']
            for b_col in bool_cols:
                if b_col in common_cols:
                    idx = common_cols.index(b_col)
                    val = vals[idx]
                    if val == 1: vals[idx] = True
                    elif val == 0: vals[idx] = False
                    
            data_batch.append(tuple(vals))
        
        try:
            with pg_conn.cursor() as pg_cur:
                psycopg2.extras.execute_batch(pg_cur, insert_sql, data_batch)
            pg_conn.commit()
            total_migrated += len(rows)
            print(f"   Processed {total_migrated} / {count}...")
        except Exception as e:
            print(f"[Error] Batch insert failed: {e}")
            pg_conn.rollback()
            break
            
    print(f"[Done] {table_name} finished.")

def _is_uuid(val):
    try:
        import uuid
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False

def run_migration():
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"[Error] SQLite DB not found at: {SQLITE_DB_PATH}")
        return

    print(f"Source: {SQLITE_DB_PATH}")
    
    try:
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        pg_conn = get_postgres_conn()
        print(f"Target: Postgres")
    except Exception as e:
        print(f"[Error] Connection failed: {e}")
        return

    # TABLES TO MIGRATE
    tables_config = [
        ("events", "id"),
        ("game_results", "event_id"), 
        ("bets", "id"), 
        ("odds_snapshots", "id"),
        ("model_predictions", "id"),
        ("action_game_enrichment", "fingerprint"), 
        ("action_injuries", "fingerprint"), 
        ("action_splits", "fingerprint"), 
        ("action_props", "fingerprint"),
        ("action_news", "fingerprint")
    ]
    
    for table, key in tables_config:
        migrate_table(pg_conn, sqlite_conn, table, conflict_key=key)
        
    # Reset Sequences
    print("\n--- Resetting Sequences ---")
    sequences = [
        ("bets_id_seq", "bets"),
        ("odds_snapshots_id_seq", "odds_snapshots"),
    ]
    
    with pg_conn.cursor() as cur:
        for seq, table in sequences:
            try:
                # Check if max id exists, default to 1
                cur.execute(f"SELECT COALESCE(MAX(id), 1) FROM {table}")
                max_id = cur.fetchone()[0]
                cur.execute(f"SELECT setval('{seq}', %s)", (max_id,))
                print(f"[Seq] Updated {seq} to {max_id}.")
            except Exception as e:
                print(f"[Seq] Skip {seq} (May not exist or table empty): {e}")
                pg_conn.rollback()
        pg_conn.commit()
    
    print("\n[Success] Migration Complete.")

if __name__ == "__main__":
    run_migration()
