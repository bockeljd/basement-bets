from src.database import get_db_connection
from ingest_dk_text import main

print("Running ingestion...")
main()

with get_db_connection() as conn:
    print("Checking DB count...")
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM bets")
    print(cursor.fetchone()[0])
