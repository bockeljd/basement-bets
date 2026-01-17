import sys
import os
import sqlite3

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.database import get_db_connection, _exec
from ingest_dk_text import main as ingest_main

def reset_and_reingest():
    print("--- RESETTING DRAFTKINGS BETS ---")
    
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # 1. Delete DK Bets
        print("Deleting existing DraftKings bets...")
        _exec(conn, "DELETE FROM bets WHERE provider='DraftKings'")
        
        # Also delete bets that might have been ingested with 'Unknown' if provider wasn't set?
        # DraftKingsTextParser defaults provider='DraftKings'.
        
        conn.commit()
        print("DraftKings bets deleted.")
        
    print("\n--- RE-INGESTING ---")
    # 2. Run Ingestion
    ingest_main()
    print("Re-ingestion complete.")

if __name__ == "__main__":
    reset_and_reingest()
