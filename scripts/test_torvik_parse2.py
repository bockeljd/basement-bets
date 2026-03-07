import requests
import pandas as pd
from bs4 import BeautifulSoup
import io

url = 'https://barttorvik.com/playerstat.php?link=y&year=2026&start=20251101&end=20260501'
ses = requests.Session()
ses.headers.update({'User-Agent': 'Mozilla/5.0'})
res = ses.post(url, data={'js_test_submitted': '1'})

soup = BeautifulSoup(res.text, 'html.parser')
tables = soup.find_all('table')
print(f"Found {len(tables)} tables")

for i, tb in enumerate(tables):
    try:
        df = pd.read_html(io.StringIO(str(tb)))[0]
        print(f"Table {i} shape: {df.shape}")
        if df.shape[1] > 10:
            print(f"Columns: {df.columns.tolist()[:10]}")
            # Try to find Duke players
            for col in df.columns:
                if 'Team' in str(col) or df[col].astype(str).str.contains('Duke').any():
                    duke_players = df[df[col] == 'Duke']
                    if not duke_players.empty:
                        print(f"--- Duke Players in Table {i} ---")
                        print(duke_players.head(5).to_string())
                    break
    except Exception as e:
        print(f"Error parsing table {i}: {e}")
