import asyncio
from playwright.async_api import async_playwright
import json
import urllib.parse
import sys
import os
sys.path.append(os.getcwd())

async def scrape_top_torvik():
    teams = ["Purdue", "Houston", "Connecticut", "Arizona", "Duke", "Iowa St.", "Auburn", "Kansas", "Alabama", "Tennessee"]
    all_players = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        for team in teams:
            search_team = "UConn" if team == "Connecticut" else team
            url = f"https://barttorvik.com/playerstat.php?link=y&team={urllib.parse.quote(search_team)}&year=2026&start=20251101&end=20260501"
            print(f"Fetching: {team}")
            try:
                await page.goto(url, wait_until='networkidle', timeout=15000)
                await page.wait_for_selector('table', timeout=10000)
                await asyncio.sleep(1)
                
                rows = await page.locator("tbody tr").all()
                for r in rows:
                    cells = await r.locator("td").all_inner_texts()
                    if len(cells) >= 15:
                        name_raw = cells[1].split('\\n')[0].strip()
                        name_team = name_raw.replace('\\n', '|').split('|')
                        actual_name = name_team[0]
                        
                        all_players.append({
                            "name": actual_name,
                            "team": team,
                            "ortg": cells[5],
                            "usg": cells[6],
                            "efg": cells[7],
                            "ts": cells[8],
                            "min_pct": cells[-1]
                        })
            except Exception as e:
                print(f"Error on {team}: {e}")
                
        # Make sure directory exists
        os.makedirs('data/imports', exist_ok=True)
        with open('data/imports/torvik_top10_2026.json', 'w') as f:
            json.dump(all_players, f, indent=2)
            
        print("Fast extraction complete!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_top_torvik())
