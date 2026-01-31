from src.database import get_db_connection, _exec

def migrate():
    print("Running migration: Adding luck & continuity to bt_team_metrics_daily...")
    with get_db_connection() as conn:
        try:
            # 1. Add luck column
            _exec(conn, """
                ALTER TABLE bt_team_metrics_daily 
                ADD COLUMN IF NOT EXISTS luck DOUBLE PRECISION;
            """)
            print("  - Added 'luck' column.")
            
            # 2. Add continuity column
            _exec(conn, """
                ALTER TABLE bt_team_metrics_daily 
                ADD COLUMN IF NOT EXISTS continuity DOUBLE PRECISION;
            """)
            print("  - Added 'continuity' column.")
            
            conn.commit()
            print("Migration complete!")
            
        except Exception as e:
            print(f"Migration failed: {e}")
            conn.rollback()

if __name__ == "__main__":
    migrate()
