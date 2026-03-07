import requests
import pandas as pd
from bs4 import BeautifulSoup
import io

url = 'https://barttorvik.com/playerstat.php?link=y&year=2026&start=20251101&end=20260501'
ses = requests.Session()
ses.headers.update({'User-Agent': 'Mozilla/5.0'})
res = ses.post(url, data={'js_test_submitted': '1'})

soup = BeautifulSoup(res.text, 'html.parser')
table = soup.find('table')
if table:
    df = pd.read_html(io.StringIO(str(table)))[0]
    duke_players = df[df.iloc[:, 1] == 'Duke'] # Assuming column 1 is team
    if duke_players.empty:
        # try to find team column
        for col in df.columns:
            if 'Team' in str(col):
                duke_players = df[df[col] == 'Duke']
                break
    print("Duke players found:")
    if not duke_players.empty:
        print(duke_players.head(10).to_string())
    else:
        print("No Duke players found in DataFrame. Columns:", df.columns)
else:
    print("No table found")
