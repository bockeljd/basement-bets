import requests
import json
import os

def check_action_raw():
    # Use a recent date with likely activity
    url = "https://api.actionnetwork.com/web/v1/scoreboard/ncaab?date=20240120" 
    # Note: 2026 is future in real life but user prompts imply 2026 context? 
    # Wait, user context says "2026-01-18". I will use today's date context.
    
    # Let's try to get a live payload for today/yesterday to ensure data presence.
    import datetime
    today = datetime.datetime.now().strftime("%Y%m%d")
    
    url = f"https://api.actionnetwork.com/web/v1/scoreboard/nfl?date={today}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
    }
    
    print(f"Fetching {url}...")
    resp = requests.get(url, headers=headers)
    print(f"Status: {resp.status_code}")
    
    if resp.status_code != 200:
        return

    data = resp.json()
    games = data.get('games', [])
    print(f"Total games: {len(games)}")
    
    if not games:
        print("No games found. Trying NCAAM...")
        url = f"https://api.actionnetwork.com/web/v1/scoreboard/ncaab?date={today}"
        resp = requests.get(url, headers=headers)
        data = resp.json()
        games = data.get('games', [])
        print(f"Total NCAAM games: {len(games)}")

    if games:
        # Dump the first game fully to inspect structure
        sample_game = games[0]
        print("\n--- SAMPLE GAME JSON ---")
        print(json.dumps(sample_game, indent=2))
        
        # Check specific enrichment fields across all games
        has_injuries = any('injuries' in str(g) for g in games)
        has_bet_stats = False
        
        # Check odds for betting percentages
        for g in games:
            odds = g.get('odds', [])
            if odds:
                first_odd = odds[0]
                # Look for percent fields
                keys = first_odd.keys()
                print(f"\nOdds Keys: {keys}")
                if any('pct' in k for k in keys) or any('percent' in k for k in keys):
                    has_bet_stats = True
                    print(f"Found stats: {first_odd}")
                    break
        
        print(f"\nHas Injuries: {has_injuries}")
        print(f"Has Bet Stats: {has_bet_stats}")

if __name__ == "__main__":
    check_action_raw()
