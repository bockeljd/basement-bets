import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec

def clean():
    print("Cleaning NCAAM predictions...")
    with get_db_connection() as conn:
        _exec(conn, "DELETE FROM model_predictions WHERE sport='NCAAM'")
        conn.commit()
    print("Done.")

if __name__ == "__main__":
    clean()
