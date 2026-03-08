import requests
import json
import os
from dotenv import load_dotenv

load_dotenv('.env')
pwd = os.environ.get('BASEMENT_PASSWORD')

def fetch_and_print(url, title):
    print(f"\n{title}")
    try:
        res = requests.get(url, headers={'X-BASEMENT-KEY': pwd})
        if res.status_code == 200:
            data = res.json()
            for b in data.get('high_confidence', [])[:5]:
                legs = " + ".join([L['team_pick'] for L in b['legs']])
                print(f"Odds: {b['american_odds']}, Legs: {legs}")
        else:
            print(res.status_code, res.text)
    except Exception as e:
        print("Error:", e)

fetch_and_print('https://basement-bets.vercel.app/api/ncaam/parlays/today?strategy=home_fav&parlay_odds_lo=-200&parlay_odds_hi=120', 'HOME FAVS')
fetch_and_print('https://basement-bets.vercel.app/api/ncaam/parlays/today', 'ALL')

