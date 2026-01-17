
from src.database import get_db_connection, _exec, get_db_type

def migrate():
    print("Migrating odds_snapshots table for Phase 4B (Decimal Precision)...")
    
    db_type = get_db_type()
    if db_type != 'postgres':
        print("Skipping column migration for SQLite (Dynamic types). Application logic will handle rounding.")
        return

    with get_db_connection() as conn:
        try:
            print("Altering columns to DECIMAL...")
            # We must drop the unique constraint first because it depends on the columns?
            # Actually, standard ALTER TYPE might work if cast is implicit. 
            # If constraint fails, we might need to recreate it.
            # Postgres usually handles type change in index if compatible. REAL -> DECIMAL is explicit cast usually.
            
            # 1. Drop Constraint
            try:
                _exec(conn, "ALTER TABLE odds_snapshots DROP CONSTRAINT odds_snapshots_event_id_market_type_side_line_book_captu_key")
            except Exception as e:
                print(f"Constraint drop failed (maybe name differs or already dropped): {e}")
                # Try finding constraint name if needed, but standard unique name might be implicit.
            
            # 2. Alter Columns
            _exec(conn, "ALTER TABLE odds_snapshots ALTER COLUMN line TYPE DECIMAL(10,1)")
            _exec(conn, "ALTER TABLE odds_snapshots ALTER COLUMN price TYPE DECIMAL(10,3)")
            
            # 3. Re-add Constraint
            _exec(conn, """
                ALTER TABLE odds_snapshots 
                ADD UNIQUE (event_id, market_type, side, line, book, captured_bucket)
            """)
            
            conn.commit()
            print("Migration complete.")
             
        except Exception as e:
            print(f"Migration failed: {e}")
            conn.rollback()

if __name__ == "__main__":
    migrate()
