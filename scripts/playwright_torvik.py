import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import io

async def get_torvik_data():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = 'https://barttorvik.com/playerstat.php?link=y&year=2026&start=20251101&end=20260501'
        print("Navigating to:", url)
        
        # Go to URL and wait for network to be idle to ensure dynamic content loads
        await page.goto(url, wait_until='networkidle', timeout=60000)
        
        # Wait specifically for the table to appear
        try:
            await page.wait_for_selector('table.tablesorter', timeout=15000)
            print("Table found!")
        except Exception as e:
            print("Timeout waiting for table:", e)
            
        html = await page.content()
        
        try:
            dfs = pd.read_html(io.StringIO(html))
            print(f"Playwright found {len(dfs)} tables.")
            for i, df in enumerate(dfs):
                if df.shape[1] > 10:
                    print(f"Table {i} is likely the stats table! Shape: {df.shape}")
                    print(f"Columns: {df.columns.tolist()[:10]}")
                    
                    # Filter to Duke
                    duke = None
                    for col in df.columns:
                        if 'Team' in str(col) or df[col].astype(str).str.contains('Duke').any():
                            duke = df[df[col] == 'Duke']
                            break
                            
                    if duke is not None and not duke.empty:
                        print("------------- DUKE PLAYERS -------------")
                        print(duke.head(10).to_string())
                        
                    # Save the big table to disk
                    df.to_csv('/tmp/torvik_stats.csv', index=False)
                    break
        except Exception as e:
            print("Pandas HTML parse error:", e)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_torvik_data())
