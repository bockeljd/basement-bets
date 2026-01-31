
import sys
import os
import argparse
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import upsert_bt_daily_schedule
from src.services.barttorvik import BartTorvikClient

def main():
    parser = argparse.ArgumentParser(description='Ingest Torvik Daily Schedule')
    parser.add_argument('--date', type=str, help='YYYYMMDD date string', default=None)
    parser.add_argument('--json', action='store_true', help='Use JSON endpoint (default)') 
    parser.add_argument('--payload_file', type=str, help='Path to local JSON file to ingest', default=None)
    args = parser.parse_args()

    date_str = args.date
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    if args.payload_file:
        import json
        print(f"[Ingest] Reading from {args.payload_file} for {date_str}...")
        with open(args.payload_file, 'r') as f:
            data = json.load(f)
        upsert_bt_daily_schedule(data, date_str)
        print("  Success (from file).")
        return

    print(f"[Ingest] Torvik Schedule for {date_str}...")
    
    client = BartTorvikClient()
    
    # We need to access the raw fetch method or use fetch_daily_projections
    # BartTorvikClient.fetch_daily_projections returns a dict of projections.
    # But we want the RAW payload list to store in DB.
    # The client method processes it. 
    # Let's check BartTorvikClient.fetch_daily_projections in src/services/barttorvik.py
    # It returns a Dict.
    # However, we want to store the raw list if possible, or we can store the processed dict?
    # The DB schema `bt_daily_schedule_raw` suggests raw JSON.
    # But `fetch_daily_projections` eats the raw response.
    # I should probably expose a raw fetch method or just sub-class/invoke requests here.
    # Actually, `fetch_daily_projections` logic is: 
    #   resp = requests.get(...)
    #   data = resp.json()
    #   ...
    #   return projections
    
    # To avoid duplicating logic/headers, let's just use requests here similarly to the client, 
    # or quick-patch the client to return raw (maybe too invasive).
    # Since this is a script, I'll just replicate the fetch logic to ensure we get exactly what the site returns
    # and store THAT.
    
    import requests
    url = f"https://barttorvik.com/schedule.php?date={date_str}&json=1"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    print(f"  Fetching from {url}...")
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if not data:
            print("  Empty response.")
            return

        print(f"  Got {len(data)} games/items. Persisting...")
        upsert_bt_daily_schedule(data, date_str)
        print("  Success.")
        
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    main()
