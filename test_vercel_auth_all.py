import requests
import json
import os
from dotenv import load_dotenv

load_dotenv('.env')
pwd = os.environ.get('BASEMENT_PASSWORD')
headers = {'X-BASEMENT-KEY': pwd}

def fetch_and_print(url, title):
    print(f"\n## {title}")
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            for b_list, limit in [('high_confidence', 5), ('payout_band', 5)]:
                if data.get(b_list) and len(data.get(b_list)) > 0:
                    print(f"--- {b_list.upper()} ---")
                    for b in data.get(b_list)[:limit]:
                        legs = " + ".join([f"{L['team_pick']} ({int(L['price'] * 100) / 100})" for L in b['legs']])
                        print(f"Odds: {b['american_odds']}, Legs: {legs}")
        else:
            print(res.status_code, res.text)
    except Exception as e:
        print("Error:", e)

fetch_and_print('https://basement-bets.vercel.app/api/ncaam/parlays/today?min_ev_per_unit=0.02&parlay_odds_lo=-120&parlay_odds_hi=300', 'MAIN')
fetch_and_print('https://basement-bets.vercel.app/api/ncaam/parlays/today?strategy=home_fav&parlay_odds_lo=-200&parlay_odds_hi=120&min_ev_per_unit=-0.2', 'HOME FAVS')

