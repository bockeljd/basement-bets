
import sys
import os

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.scrapers.user_fanduel_pw import FanDuelScraperPW

if __name__ == "__main__":
    print("Starting Playwright Validation...")
    try:
        scraper = FanDuelScraperPW()
        print("Launching scraper...")
        # running directly to see stdout
        text = scraper.scrape()
        print(f"Scrape Result Length: {len(text)}")
        if len(text) < 1000:
            print("WARNING: Scraped text seems too short. Likely failed to load history.")
            print("Snippet:", text[:500])
        else:
            print("Success! Data looks substantial.")
            
    except Exception as e:
        print(f"Validation Failed: {e}")
