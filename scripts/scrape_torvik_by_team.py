import asyncio
from playwright.async_api import async_playwright
import json
import urllib.parse
import sys
import os
sys.path.append(os.getcwd())
from src.database import get_db_connection

async def scrape_torvik_teams():
    # Get top 68 KenPom teams
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT team_name FROM kenpom_ratings ORDER BY rank ASC LIMIT 68")
        teams = [r[0] for r in cur.fetchall()]
        
    print(f"Scraping {len(teams)} teams from Torvik...")
    
    all_players = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        for team in teams:
            try:
                # Torvik team names sometimes differ completely (e.g. "Connecticut" vs "UConn")
                # But for the most part we'll try the exact name or common variants
                search_team = "UConn" if team == "Connecticut" else team
                
                url = f"https://barttorvik.com/playerstat.php?link=y&team={urllib.parse.quote(search_team)}&year=2026&start=20251101&end=20260501"
                print(f"  Fetching: {search_team}")
                await page.goto(url, wait_until='networkidle', timeout=15000)
                await page.wait_for_selector('table', timeout=10000)
                await asyncio.sleep(1.5)
                
                rows = await page.locator("tbody tr").all()
                team_count = 0
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
                        team_count += 1
                print(f"    Found {team_count} players")
            except Exception as e:
                print(f"    Error on {team}: {e}")
                
        # Save results
        with open('data/imports/torvik_2026_players.json', 'w') as f:
            json.dump(all_players, f, indent=2)
            
        print(f"Extraction complete! Saved {len(all_players)} total players.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_torvik_teams())
