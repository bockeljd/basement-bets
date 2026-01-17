import requests
import json

def check_action_raw():
    url = "https://api.actionnetwork.com/web/v1/scoreboard/ncaab?date=20260113"
    headers = {
        'User-Agent': 'Mozilla/5.0'
    }
    resp = requests.get(url, headers=headers)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    games = data.get('games', [])
    print(f"Total games for 1/13: {len(games)}")
    for g in games:
        print(f"\nGame ID: {g.get('id')} - {g.get('status')} - {g.get('start_time')}")
        box = g.get('boxscore', {})
        print(f"  Boxscore: {box}")
        for t in g.get('teams', []):
            print(f"    - {t.get('full_name')} (ID: {t.get('id')}) Score: {t.get('score')}")

if __name__ == "__main__":
    check_action_raw()
