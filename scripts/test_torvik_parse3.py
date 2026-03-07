import requests
import json
import re

url = 'https://barttorvik.com/playerstat.php?link=y&year=2026&start=20251101&end=20260501'
ses = requests.Session()
ses.headers.update({'User-Agent': 'Mozilla/5.0'})
res = ses.post(url, data={'js_test_submitted': '1'})

print("Content length:", len(res.text))

# Find script tags containing 'var players =' or similar
matches = re.finditer(r'var\s+[\w_]+\s*=\s*(\[.*\]);', res.text)
for match in matches:
    data = match.group(1)
    try:
        parsed = json.loads(data)
        if isinstance(parsed, list) and len(parsed) > 50:
            print("Found large JSON array variable:", len(parsed), "items")
            print("Item 0:", parsed[0])
            break
    except Exception:
        pass

# Also look for 'data = [' if present
if 'data = [[' in res.text:
    idx = res.text.find('data = [[')
    end_idx = res.text.find('];', idx)
    try:
        parsed = json.loads(res.text[idx + 7:end_idx + 1])
        print("Found data = [[...]] array:", len(parsed), "items")
        print("Item 0:", parsed[0])
    except Exception as e:
        print("Error parsing data array:", e)

    
