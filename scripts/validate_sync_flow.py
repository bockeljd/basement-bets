
import requests
import json
import sqlite3
import psycopg2
import sys
import os

# The cURL provided by the user (simulating the frontend payload)
CURL_DATA = """curl 'https://api.sportsbook.fanduel.com/sbapi/fetch-my-bets?isSettled=true&fromRecord=1&toRecord=20&sortDir=DESC&sortParam=SETTLEMENT_DATE&adaptiveTokenEnabled=false&_ak=FhMFpcPWXMeyZxOx' \
  -H 'accept: application/json' \
  -H 'accept-language: en-US,en;q=0.9' \
  -H 'origin: https://oh.sportsbook.fanduel.com' \
  -H 'priority: u=1, i' \
  -H 'referer: https://oh.sportsbook.fanduel.com/' \
  -H 'sec-ch-ua: "Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"' \
  -H 'sec-ch-ua-mobile: ?0' \
  -H 'sec-ch-ua-platform: "macOS"' \
  -H 'sec-fetch-dest: empty' \
  -H 'sec-fetch-mode: cors' \
  -H 'sec-fetch-site: same-site' \
  -H 'user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36' \
  -H 'x-app-version: 2.135.2' \
  -H 'x-application: FhMFpcPWXMeyZxOx' \
  -H 'x-authentication: eyJraWQiOiIyIiwiYWxnIjoiUlMyNTYifQ.eyJzZXMiOjg5OTU3NDQ3NzIsInN1YiI6NDAwOTE0MywicHJkIjoiU0IiLCJjcnQiOjE3NjkzNTI2MzEsImVtbCI6ImJvY2tlbGpkQGdtYWlsLmNvbSIsInNyYyI6MSwibWZhIjp0cnVlLCJ0eXAiOjEsInBybSI6eyJ1aWQiOiIwMUtGVFQ1NEhFRlZWTVhIOU5RVkY5M1Y4SyIsImxvYyI6eyJwcnMiOlsiU0IiXSwiYWNyIjoiT0giLCJyZWciOmZhbHNlLCJpcCI6IjE2Mi4xOTQuMTYzLjEzMSIsInJlciI6Ik9IIiwiY255IjoiVVMifSwicHJkIjoiU0IiLCJkbmwiOltdLCJncnQiOnsicmlzIjoiTUEiLCJyaWMiOiJVTklURURfU1RBVEVTIiwiYWdlIjozN30sImV4cCI6IjIwMjYtMDEtMjZUMDQ6MDg6NTUuNzk0MjYxMjU2WiJ9LCJ1c24iOiJqYm9jazEwIiwicmxzIjpbMV0sImV4cCI6MTc2OTM1NzMzNSwicmVyIjoiT0gifQ.yRmYwT-6FKl1jocQnjJlNPtR4Ol3NxxREQgAiaXeEVI6NdyapPICyalse-g2qfELuQj-WNzzVuho3KulUII3-JFGHqtzwmOfMOhKPIOe8b1M2f2wK_c0o5QTZGT9xSl1ZhdOS0MeiwQYmuyJCftMaSN35D5raclBUdXKZx6viTuepQ9-48ZMZtZlmbQLPAHrGhEQBdANo_vpsw3ap-cQGlCAM1BTFNibPZQUfQUDnHuCV8KXJ57ELJG0DnMg8oMZuFnjuqij8BF_Pa2JCSZHNF46znvH-ml6D_2Cn-k_KR30cNO8nJeM00iVnuWSJ1tTg__kDlfdHHjRjnnAdJZCsw' \
  -H 'x-px-context: _pxvid=a7d8f1a0-ef60-11f0-b9c7-8311842733b5;pxcts=a7d8f8b1-ef60-11f0-b9c8-2069a4c1f4f1;' \
  -H 'x-sportsbook-region: OH'"""

def validate():
    print("1. Sending Request to API (simulating button click)...")
    url = "http://localhost:8000/api/sync/fanduel/token"
    
    # Auth Header (local password)
    headers = {
        "X-BASEMENT-KEY": "moneyneversleeps"
    }
    
    try:
        resp = requests.post(url, json={"curl_or_token": CURL_DATA}, headers=headers)
        if resp.status_code == 200:
            print("   ✅ Success! API Response:", resp.json())
        else:
            print(f"   ❌ Failed. Status: {resp.status_code}")
            print("   Response:", resp.text)
            return
    except Exception as e:
        print(f"   ❌ Network Error: {e}")
        return

    print("\n2. Verifying Database Injection...")
    # Read DATABASE_URL from .env or assume local
    # Assuming standard psycopg2 connection, but using direct script logic for simplicity
    # Just need simple count check.
    
    # Actually, we can just hit the API to get bets if available, or just trust the response.
    # But let's check DB directly to be sure.
    
    # Note: Env vars might not be loaded in python script safely.
    # I'll rely on the API response 'bets_saved' for now, 
    # OR I can hit GET /api/bets/manual ?? No, GET /api/bets
    
    print("   Fetching recent bets via API to confirm storage...")
    try:
        bets_resp = requests.get("http://localhost:8000/api/bets", headers=headers)
        if bets_resp.status_code == 200:
            all_bets = bets_resp.json()
            # Filter for FanDuel
            fd_bets = [b for b in all_bets if b.get('provider') == 'FanDuel']
            print(f"   ✅ Found {len(fd_bets)} FanDuel bets in database.")
            if fd_bets:
                print("   Latest Bet:")
                print(f"   {fd_bets[0].get('date')} | {fd_bets[0].get('description')} | ${fd_bets[0].get('wager')} -> ${fd_bets[0].get('profit')}")
        else:
            print("   ⚠️ Could not fetch bets list.")
    except:
        print("   ⚠️ Could not connect to API for verification.")

if __name__ == "__main__":
    validate()
