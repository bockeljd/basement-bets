
from src.database import get_db_connection

def check_schema():
    print("--- Checking model_predictions Schema ---")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'model_predictions'")
        rows = cur.fetchall()
        print([r[0] for r in rows])

if __name__ == "__main__":
    check_schema()
