
from src.database import get_db_connection

def check_users():
    print("--- User ID Distribution in Bets ---")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, COUNT(*) FROM bets GROUP BY user_id")
        rows = cur.fetchall()
        for r in rows:
            print(f"User: '{r[0]}' | Count: {r[1]}")

if __name__ == "__main__":
    check_users()
