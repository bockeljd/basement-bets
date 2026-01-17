import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.database import get_db_connection

def check_count():
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT count(*) FROM bets")
            print(f"Total Bets: {c.fetchone()[0]}")
            
            c.execute("SELECT count(*) FROM bets WHERE raw_text LIKE 'Legacy Import%'")
            print(f"Legacy Bets: {c.fetchone()[0]}")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    check_count()
