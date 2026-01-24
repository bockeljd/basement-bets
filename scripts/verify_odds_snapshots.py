
from src.database import get_db_connection, _exec
import pandas as pd

def run_queries():
    queries = {
        "Confirm coverage for core markets": """
            SELECT e.league,
                   o.market_type,
                   COUNT(*) AS rows,
                   COUNT(DISTINCT o.event_id) AS events_covered
            FROM odds_snapshots o
            JOIN events e ON e.id = o.event_id
            GROUP BY 1,2
            ORDER BY 1,2;
        """,
        "Validate uniqueness key": """
            SELECT event_id, market_type, side, line, book, captured_bucket, COUNT(*) AS n
            FROM odds_snapshots
            GROUP BY 1,2,3,4,5,6
            HAVING COUNT(*) > 1
            ORDER BY n DESC
            LIMIT 50;
        """
    }
    
    with get_db_connection() as conn:
        for name, sql in queries.items():
            print(f"\n=== {name} ===")
            try:
                # Use pandas for pretty output
                df = pd.read_sql(sql, conn)
                print(df.to_string(index=False))
            except Exception as e:
                print(f"Query Error: {e}")

if __name__ == "__main__":
    run_queries()
