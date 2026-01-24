
import requests
import os
from dotenv import load_dotenv
import time

load_dotenv()
PASSWORD = os.getenv("BASEMENT_PASSWORD", "letmein123")
HEADERS = {"X-BASEMENT-KEY": PASSWORD}
BASE_URL = "http://localhost:8000/api"

def verify_clv_flow():
    print("[Verify] Starting CLV & Metrics Verification...")
    
    # 1. Check History for New Columns
    print("\n-- 1. Checking Schema in History --")
    res = requests.get(f"{BASE_URL}/ncaam/history", headers=HEADERS)
    if res.status_code == 200:
        hist = res.json()
        if hist:
            sample = hist[0]
            # Check for new columns
            new_cols = ['edge_points', 'open_line', 'clv_points']
            found = [c for c in new_cols if c in sample]
            print(f"[Info] Found metrics columns: {found}")
            if len(found) == len(new_cols):
                print("[Pass] API returns new first-class metric columns (even if null).")
            else:
                # They might be null but keys should exist if row dict is fully populated? 
                # Or maybe SQL returns None and python dict keeps it.
                # Actually, older rows might have nulls.
                # But fields should be present in the keys.
                print(f"[Warn] Missing some columns in sample keys: {list(sample.keys())}")
        else:
            print("[Info] No history rows to check schema.")
    else:
        print(f"[Fail] History API Error: {res.status_code}")

    # 2. Trigger Analysis (Should Populate Open Line)
    # We need a game ID.
    print("\n-- 2. Triggering Analysis (Populate Open Line) --")
    board = requests.get(f"{BASE_URL}/ncaam/board", headers=HEADERS).json()
    if board:
        target = board[0]
        # Ensure we have odds? Board info implies odds exist.
        if target.get('home_spread') is not None:
            print(f"Analyzing {target['home_team']} vs {target['away_team']}...")
            an_res = requests.post(f"{BASE_URL}/analyze/{target['id']}", headers=HEADERS, json={
                "sport": "NCAAM", 
                "home_team": target['home_team'], 
                "away_team": target['away_team']
            })
            if an_res.status_code == 200:
                print("[Pass] Analysis successful.")
                data = an_res.json()
                if 'open_line' in data or 'bet_line' in data:
                    print(f"       Result contains metric fields: open_line={data.get('open_line')}, edge={data.get('edge_points')}")
            else:
                print(f"[Fail] Analysis failed: {an_res.text}")
        else:
            print("[Skip] No odds for first game on board.")
    else:
        print("[Skip] No games on board.")

    # 3. Simulate Grading (Compute CLV)
    # CLV only computes if start_time < now. 
    # Unless we force it or rely on existing finished games.
    print("\n-- 3. Triggering Grading (Compute CLV) --")
    g_res = requests.post(f"{BASE_URL}/research/grade", headers=HEADERS)
    if g_res.status_code == 200:
        print(f"[Pass] Grading triggered. Updates: {g_res.json()}")
    else:
        print(f"[Fail] Grading failed: {g_res.text}")

if __name__ == "__main__":
    verify_clv_flow()
