import requests
import json
import os
from dotenv import load_dotenv

load_dotenv('.env')
pwd = os.environ.get('BASEMENT_PASSWORD')

res = requests.get('https://basement-bets.vercel.app/api/ncaam/parlays/today?strategy=home_fav&parlay_odds_lo=-200&parlay_odds_hi=120&min_ev_per_unit=-0.2', headers={'X-BASEMENT-KEY': pwd})
if res.status_code == 200:
    data = res.json()
    print("## Home Favorites")
    for b in data.get('high_confidence', [])[:5]:
        legs = " + ".join([L['team_pick'] for L in b['legs']])
        print(f"Odds: {b['american_odds']}, Legs: {legs}")
else:
    print(res.status_code, res.text)
