import os
import psycopg2
from src.database import get_db_connection

def test_conn():
    print(f"Testing connection...")
    try:
        url = os.environ.get('DATABASE_URL')
        if not url:
            print("ERROR: DATABASE_URL env var is missing!")
            return
            
        print(f"URL found (len={len(url)})")
        # Mask password for safety
        print(f"URL prefix: {url.split('@')[0].split(':')[0]}...")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                res = cur.fetchone()
                print(f"Success! Result: {res}")
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    test_conn()
