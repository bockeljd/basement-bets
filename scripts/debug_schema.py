
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_db_connection, _exec

def inspect_schema():
    print("Inspecting odds_snapshots schema...")
    query = """
    SELECT column_name, data_type, column_default, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'odds_snapshots'
    ORDER BY ordinal_position;
    """
    with get_db_connection() as conn:
        rows = _exec(conn, query).fetchall()
        for r in rows:
            print(f"{r['column_name']}: {r['data_type']} [Default: {r['column_default']}] [Nullable: {r['is_nullable']}]")

if __name__ == "__main__":
    inspect_schema()
