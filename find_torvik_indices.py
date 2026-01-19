import requests
import json

url = "https://barttorvik.com/2026_team_results.json"
print(f"Fetching {url}...")
try:
    resp = requests.get(url, timeout=10)
    data = resp.json()
    if data:
        print("First row data:")
        row = data[0]
        for i, val in enumerate(row):
            print(f"{i}: {val}")
            
        # Try to find Duke to check recognizable stats
        for r in data:
            if "Duke" in str(r[1]):
                print("\nDuke Row:")
                for i, val in enumerate(r):
                    print(f"{i}: {val}")
                break
except Exception as e:
    print(e)
