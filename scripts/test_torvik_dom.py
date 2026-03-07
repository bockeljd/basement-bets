import asyncio
from playwright.async_api import async_playwright

async def test_dom():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://barttorvik.com/playerstat.php?link=y&team=Duke&year=2026", wait_until='networkidle')
        await page.wait_for_selector('table tbody tr')
        await asyncio.sleep(2)
        
        # Log exactly what is in the first row
        row = page.locator("tbody tr").first
        html = await row.inner_html()
        print("Row HTML:", html)
        
        cells = await row.locator("td").all()
        for i, c in enumerate(cells):
            text = await c.inner_text()
            print(f"Cell {i}: {repr(text)}")
        await browser.close()

asyncio.run(test_dom())
