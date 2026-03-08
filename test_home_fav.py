import asyncio
import os
import sys
sys.path.append(os.getcwd())
from src.api import get_ncaam_parlays_today

async def main():
    try:
        data = await get_ncaam_parlays_today(strategy='home_fav', parlay_odds_lo=-200, parlay_odds_hi=120)
        print("Data keys:", data.keys())
        print("## Home Favorites")
        for b in data.get('high_confidence', [])[:5]:
            legs = " + ".join([f"{L['team_pick']} ({L['price']})" for L in b['legs']])
            print(f"Odds: {b['american_odds']}, Legs: {legs}")
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
