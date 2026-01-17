
from src.database import get_db_connection, _exec, init_model_health_db

if __name__ == "__main__":
    print("Dropping model_health_daily...")
    with get_db_connection() as conn:
        _exec(conn, "DROP TABLE IF EXISTS model_health_daily")
        conn.commit()
    
    print("Re-creating model_health_daily...")
    init_model_health_db()
    print("Done.")
