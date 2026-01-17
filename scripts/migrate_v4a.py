
from src.database import get_db_connection, _exec

def migrate():
    print("Migrating bet_legs table for Phase 4A...")
    
    with get_db_connection() as conn:
        # 1. Link Status
        try:
            print("Adding link_status column...")
            _exec(conn, "ALTER TABLE bet_legs ADD COLUMN link_status TEXT DEFAULT 'PENDING'")
            conn.commit()
        except Exception as e:
            print(f"link_status add failed: {e}")
            conn.rollback()

        # 2. Side
        try:
            print("Adding side column...")
            _exec(conn, "ALTER TABLE bet_legs ADD COLUMN side TEXT")
            conn.commit()
        except Exception as e:
            print(f"side add failed: {e}")
            conn.rollback()

        # 3. Selection Team ID
        try:
            print("Adding selection_team_id column...")
            _exec(conn, "ALTER TABLE bet_legs ADD COLUMN selection_team_id TEXT")
            conn.commit()
        except Exception as e:
            print(f"selection_team_id add failed: {e}")
            conn.rollback()

    print("Migration complete.")

if __name__ == "__main__":
    migrate()
