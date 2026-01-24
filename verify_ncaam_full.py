
import requests
import sys
import os
from dotenv import load_dotenv

load_dotenv()
PASSWORD = os.getenv("BASEMENT_PASSWORD", "letmein123") # Default known password or env

headers = {
    "X-BASEMENT-KEY": PASSWORD
}

BASE_URL = "http://localhost:8000/api"

def verify_full_ncaam():
    print("[Verify] Starting Comprehensive NCAAM Verification...")
    
    # 1. Verify Board (SQLite/Postgres Compat)
    print("\n-- 1. Testing /api/ncaam/board --")
    try:
        res = requests.get(f"{BASE_URL}/ncaam/board", headers=headers)
        if res.status_code == 200:
            data = res.json()
            print(f"[Pass] Board returned {len(data)} games.")
            if len(data) > 0:
                print(f"       Sample: {data[0].get('home_team')} vs {data[0].get('away_team')}")
                print(f"       Keys: {list(data[0].keys())}")
        else:
            print(f"[FAIL] Board Failed: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"[FAIL] Board Exception: {e}")

    # 2. Verify Analysis (Setup for grading)
    # Use the game ID from board if available, else skip
    game_id = None
    try:
        res = requests.get(f"{BASE_URL}/ncaam/board")
        data = res.json()
        if data:
            target = data[0]
            game_id = target['id']
            # Analyze it
            print(f"\n-- 2. Analyzing Game {game_id} --")
            an_res = requests.post(f"{BASE_URL}/analyze/{game_id}", headers=headers, json={
                "sport": "NCAAM", 
                "home_team": target['home_team'], 
                "away_team": target['away_team']
            })
            if an_res.status_code == 200:
                print("[Pass] Analysis success.")
            else:
                print(f"[FAIL] Analysis failed: {an_res.text}")
    except:
        pass

    # 3. Verify Grading
    print("\n-- 3. Testing /api/research/grade --")
    try:
        res = requests.post(f"{BASE_URL}/research/grade", headers=headers)
        if res.status_code == 200:
            print(f"[Pass] Grading response: {res.json()}")
        else:
            print(f"[FAIL] Grading Failed: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"[FAIL] Grading Exception: {e}")

    # 4. Verify History Schema
    print("\n-- 4. Testing /api/ncaam/history --")
    try:
        res = requests.get(f"{BASE_URL}/ncaam/history", headers=headers)
        if res.status_code == 200:
            hist = res.json()
            print(f"[Pass] History returned {len(hist)} rows.")
            if len(hist) > 0:
                print(f"       Keys: {list(hist[0].keys())}")
                if 'final_score_home' in hist[0] and 'graded_result' in hist[0]:
                    print("[Pass] History schema contains enriched fields.")
                else:
                    print("[FAIL] Enriched fields missing from history.")
        else:
            print(f"[FAIL] History Failed: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"[FAIL] History Exception: {e}")

if __name__ == "__main__":
    verify_full_ncaam()
