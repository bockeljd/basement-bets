import asyncio
import os
import sys

sys.path.append(os.getcwd())

from src.api import get_ncaam_parlays_today

async def main():
    try:
        data = await get_ncaam_parlays_today(parlay_odds_lo=-120, parlay_odds_hi=300)
        
        print("## Highest Confidence")
        for b in data.get('high_confidence', [])[:5]:
            legs = " + ".join([f"{L['team_pick']} ({int(L['price'] * 100) / 100})" for L in b['legs']])
            print(f"Odds: {b['american_odds']}, Legs: {legs}")

        print("\n## Value Matchups")
        for b in data.get('payout_band', [])[:5]:
            legs = " + ".join([f"{L['team_pick']} ({int(L['price'] * 100) / 100})" for L in b['legs']])
            print(f"Odds: {b['american_odds']}, Legs: {legs}")

        home = await get_ncaam_parlays_today(strategy='home_fav', parlay_odds_lo=-200, parlay_odds_hi=120, min_ev_per_unit=-0.2)
        print("\n## Home Favorites")
        for b in home.get('high_confidence', [])[:5]:
            legs = " + ".join([f"{L['team_pick']} ({int(L['price'] * 100) / 100})" for L in b['legs']])
            print(f"Odds: {b['american_odds']}, Legs: {legs}")
            
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
