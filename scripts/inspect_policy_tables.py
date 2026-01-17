
from src.database import get_db_connection, _exec

if __name__ == "__main__":
    print("--- Model Health Daily ---")
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT * FROM model_health_daily").fetchall()
        for r in rows:
            print(dict(r))
            
    print("--- Market Allowlist ---")
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT * FROM market_allowlist").fetchall()
        for r in rows:
            print(dict(r))
            
    print("\n--- Model Registry ---")
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT * FROM model_registry").fetchall()
        for r in rows:
            print(dict(r))
            
    print("\n--- Policy Decisions ---")
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT * FROM policy_decisions").fetchall()
        for r in rows:
            print(dict(r))
