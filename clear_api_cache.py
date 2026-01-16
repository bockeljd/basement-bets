from src.database import get_db_connection, _exec

with get_db_connection() as conn:
    print("Clearing API Cache...")
    _exec(conn, "DELETE FROM api_cache")
    conn.commit()
    print("Cache Cleared.")
