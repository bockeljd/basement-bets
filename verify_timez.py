
import requests
import os
import sys
# Add project root needed for DB access? 
# Actually just use API if it exposes raw strings.
# Or use script to query DB directly.

sys.path.append(os.path.join(os.path.dirname(__file__), "."))
from src.database import get_db_connection, _exec, get_db_type
from dotenv import load_dotenv

load_dotenv()
PASSWORD = os.getenv("BASEMENT_PASSWORD", "letmein123")
HEADERS = {"X-BASEMENT-KEY": PASSWORD}

def verify_timez():
    print("--- Timezone Audit ---")
    
    # 1. Check DB Raw Value
    query = "SELECT id, home_team, start_time FROM events WHERE league='NCAAM' ORDER BY start_time DESC LIMIT 1"
    with get_db_connection() as conn:
        try:
            row = _exec(conn, query).fetchone()
            if row:
                print(f"[DB Raw] {row['home_team']}: {row['start_time']} (Type: {type(row['start_time'])})")
            else:
                print("[DB] No events found.")
        except Exception as e:
            print(f"[DB Error] {e}")

    # 2. Check API Output
    try:
        res = requests.get("http://localhost:8000/api/ncaam/history", headers=HEADERS)
        if res.status_code == 200:
            hist = res.json()
            if hist:
                item = hist[0]
                print(f"[API History] Analyzed At: {item.get('analyzed_at')}")
                print(f"[API History] Start Time: {item.get('start_time')}")
    except Exception as e:
        print(f"[API] Failed: {e}")

if __name__ == "__main__":
    verify_timez()
