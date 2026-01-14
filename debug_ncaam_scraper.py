import pandas as pd
import requests

url = "https://www.sports-reference.com/cbb/seasons/men/2026-advanced-school-stats.html"
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}
resp = requests.get(url, headers=headers)
print(f"Response: {resp.status_code}")

try:
    dfs = pd.read_html(resp.text)
    if dfs:
        df = dfs[0]
        print("Columns (Raw):")
        print(df.columns)
        
        # Try flattening
        if isinstance(df.columns, pd.MultiIndex):
            print("\nMultiIndex Detected. Levels:")
            print(df.columns.levels)
            
            flat_cols = df.columns.map(lambda x: x[1] if "Unnamed" not in x[1] else x[0])
            print("\nFlattened Columns:")
            print(flat_cols)
            
            df.columns = flat_cols
            print("\nCheck for required cols:")
            for c in ['Pace', 'ORtg', 'DRtg']:
                print(f"{c}: {c in df.columns}")
    else:
        print("No tables found.")
except Exception as e:
    print(f"Error: {e}")
