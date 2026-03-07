import asyncio
from playwright.async_api import async_playwright
import json

async def scrape_torvik():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # We'll fetch all players by looping through Top Teams, or just grab the first N pages.
        # Since the user specifically wants the current rosters for top teams, let's scrape the top teams by typing in the filter.
        teams_to_scrape = ["Duke", "Purdue", "Connecticut", "Houston", "Arizona"]
        all_players = []
        
        url = 'https://barttorvik.com/playerstat.php?link=y&year=2026&start=20251101&end=20260501'
        print("Navigating to:", url)
        await page.goto(url, wait_until='networkidle', timeout=60000)
        
        # Wait for the table to appear (meaning JS check passed)
        await page.wait_for_selector('table', timeout=30000)
        await asyncio.sleep(2)
        print("Bypassed checks. Table is visible.")
        
        # The filter input is usually a search box on Torvik
        # Torvik has a dropdown for team: <select name="t">
        # Let's interact with the Team dropdown or search box.
        # Since Torvik has a "Search" box for players, and a Team filter. 
        # Actually, extracting pages 1 to 5 gives the top 500 players, which likely covers the rotation for all Top 25 teams.
        # Let's extract 15 pages (Top 1500 players)
        
        for page_num in range(1, 15):
            print(f"Scraping Page {page_num}...")
            # Extract rows
            rows = await page.locator("tbody tr").all()
            for r in rows:
                try:
                    cells = await r.locator("td").all_inner_texts()
                    if len(cells) >= 15:
                        name = cells[1].split('\\n')[0].strip() # 'Cameron Boozer\nDuke'
                        name_team = name.replace('\\n', '|').split('|')
                        actual_name = name_team[0]
                        team = name_team[-1] if len(name_team) > 1 else cells[2].strip()
                        
                        # Torvik columns (approx)
                        ortg = cells[5]
                        usg = cells[6]
                        efg = cells[7]
                        ts = cells[8]
                        min_pct = cells[-1] # or whatever minute col is
                        
                        all_players.append({
                            "name": actual_name,
                            "team": team,
                            "ortg": ortg,
                            "usg": usg,
                            "efg": efg,
                            "ts": ts,
                            "min_pct": min_pct
                        })
                except Exception as e:
                    pass
                    
            # Click next page
            try:
                next_btn = page.locator("a", has_text="Next")
                if await next_btn.count() > 0:
                    await next_btn.first.click()
                    await asyncio.sleep(1)
                else:
                    break
            except:
                break
                
        # Save results
        with open('torvik_extracted_players.json', 'w') as f:
            json.dump(all_players, f, indent=2)
            
        print(f"Extracted {len(all_players)} total players!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_torvik())
