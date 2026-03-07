import requests
import json
import re

url = 'https://barttorvik.com/playerstat.php?link=y&year=2026&start=20251101&end=20260501'
ses = requests.Session()
ses.headers.update({'User-Agent': 'Mozilla/5.0'})
res = ses.post(url, data={'js_test_submitted': '1'})

# find the JSON that looks like a 2D array of stats
# usually starts with a large array of arrays where first element is player name
match = re.search(r'var data\s*=\s*(\[\[.*?\]\]);', res.text, re.DOTALL)
if match:
    data_str = match.group(1)
    try:
        data = json.loads(data_str)
        print(f"Parsed 'data' array with {len(data)} rows")
        
        # let's look at the first row to determine column indexes
        print("Row 0:", data[0])
        print("Row 100:", data[100])
        
        # save to file for exploration
        with open('torvik_extracted.json', 'w') as f:
            json.dump(data, f)
            
    except Exception as e:
        print("JSON parse error on 'data':", e)
else:
    print("Could not find 'var data = ...' array")
    # try another variable format
    match2 = re.search(r'\[\[".*?\]\]', res.text, re.DOTALL)
    if match2:
        try:
            data = json.loads(match2.group(0))
            print(f"Parsed anonymous array with {len(data)} rows")
            print("Row 0:", data[0])
        except:
            print("Failed fallback array parse")
