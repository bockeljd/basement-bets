import asyncio
import os
import sys

# Add the project root to sys.path
sys.path.append(os.getcwd())

from src.api import get_ncaam_parlays_today

async def main():
    try:
        data = await get_ncaam_parlays_today()
        
        print("## Highest Confidence")
        for b in data.get('high_confidence', [])[:5]:
            legs = " + ".join([L['team_pick'] for L in b['legs']])
            print(f"Odds: {b['american_odds']}, Legs: {legs}")

        print("\n## Value Matchups (Payout Band)")
        for b in data.get('payout_band', [])[:5]:
            legs = " + ".join([L['team_pick'] for L in b['legs']])
            print(f"Odds: {b['american_odds']}, Legs: {legs}")
            
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
