import asyncio
from playwright.async_api import async_playwright
import json

async def capture_xhr():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Listen for all responses
        async def handle_response(response):
            try:
                if 'json' in response.headers.get('content-type', '').lower() or '.json' in response.url:
                    text = await response.text()
                    if len(text) > 10000:
                        print(f"FOUND LARGE JSON ENDPOINT: {response.url} ({len(text)} bytes)")
                        if "Boozer" in text or "Duke" in text:
                            print(f"  --> Contains Duke players!")
                            with open('/tmp/torvik_xhr_api.txt', 'w') as f:
                                f.write(response.url)
            except Exception:
                pass
                
        page.on("response", handle_response)
        
        url = 'https://barttorvik.com/playerstat.php?link=y&year=2026&start=20251101&end=20260501'
        print("Navigating to:", url)
        await page.goto(url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(2)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_xhr())
