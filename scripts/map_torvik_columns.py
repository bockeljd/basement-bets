import requests
import pandas as pd
from io import StringIO

url = "https://barttorvik.com/trank.php?year=2026"
json_url = "https://barttorvik.com/2026_team_results.json"

print(f"Fetching HTML from {url}...")
headers = {"User-Agent": "Mozilla/5.0"}
try:
    html_resp = requests.get(url, headers=headers, timeout=15)
    html_content = html_resp.text
    
    # Use pandas to parse tables
    dfs = pd.read_html(StringIO(html_content))
    print(f"Found {len(dfs)} tables.")
    
    main_table = None
    for df in dfs:
        if len(df) > 300: # The main table has 360+ teams
            main_table = df
            break
            
    if main_table is not None:
        print("Main Table Columns:")
        print(main_table.columns.tolist())
        
        # Get first row (usually Michigan or top rank)
        print("\nFirst HTML Row:")
        print(main_table.iloc[0])
        
        print("\nFetching JSON...")
        json_resp = requests.get(json_url, headers=headers, timeout=15)
        json_data = json_resp.json()
        
        # Find the same team in JSON
        team_name = main_table.iloc[0]['Team'] # Adjust if column name differs
        # Torvik HTML usually has 'Team', 'AdjOE', 'AdjDE', etc.
        
        # Clean team name (remove seed/conf)
        # HTML might have "Michigan 16-1 (6-1)"
        
        print("\nSearching for match in JSON...")
        for row in json_data:
            # Row[1] is name
            if row[1] in str(team_name) or str(team_name) in row[1]:
                print(f"JSON Match Found: {row[1]}")
                print("JSON Row Indices:")
                for i, v in enumerate(row):
                    print(f"{i}: {v}")
                break
                
    else:
        print("Could not find main table.")
        print("\nRaw HTML around 'Michigan' (first 1000 chars of match):")
        idx = html_content.find("Michigan")
        if idx != -1:
            print(html_content[idx:idx+2000])
        else:
            print("Michigan not found in HTML.")
        
except Exception as e:
    print(f"Error: {e}")
    if 'html_content' in locals() and html_content:
        print("\nRaw HTML around 'Michigan':")
        idx = html_content.find("Michigan")
        if idx != -1:
            print(html_content[idx:idx+2000])
        else:
            print("Michigan not found. Dumping first 500 chars:")
            print(html_content[:500])
