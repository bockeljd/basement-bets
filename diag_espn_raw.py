import requests
import json

url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
params = {'limit': 1000, 'groups': 50}
resp = requests.get(url, params=params)
data = resp.json()
events = data.get('events', [])
print(f"Total ESPN Events for today: {len(events)}")
for i, ev in enumerate(events[:5]):
    print(f"{i}: {ev.get('name')} | {ev.get('date')}")
