
import logging
import traceback
from src.selenium_client import SeleniumClient
from src.parsers.draftkings_text import DraftKingsTextParser
from bs4 import BeautifulSoup

class DraftKingsService:
    def __init__(self, profile_path="./chrome_profile"):
        self.profile_path = profile_path

    def scrape_history(self):
        """
        Launches Selenium, scrapes 'Settled' bets, and returns parsed bet objects.
        """
        print("🚀 Launching DraftKings Scraper Service...")
        client = None
        try:
            # 1. Launch Browser
            client = SeleniumClient(headless=False, profile_path=self.profile_path)
            
            # 2. Scrape HTML
            html = client.scrape_draftkings_bets()
            if not html:
                raise Exception("Failed to retrieve HTML from DraftKings.")

            print("✅ HTML Retrieved. Parsing...")
            
            # 3. Clean & Parse
            soup = BeautifulSoup(html, "html.parser")
            bet_container = soup.find("div", {"class": "my-bets-pane"})
            
            if bet_container:
                raw_text = bet_container.get_text(separator="\n", strip=True)
            else:
                raw_text = soup.get_text(separator="\n", strip=True)
                
            parser = DraftKingsTextParser()
            bets = parser.parse(raw_text)
            
            print(f"💰 Parsed {len(bets)} bets.")
            return bets

        except Exception as e:
            print(f"❌ DK Service Error: {e}")
            traceback.print_exc()
            raise e
        finally:
            if client:
                print("🛑 Closing Browser...")
                # We do NOT use input() pause here because this is an API service.
                # However, for debugging, maybe we want to leave it open?
                # User asked to "integrate scraping logic", usually API calls should close resources.
                # But 'detach' is removed, so 'client.quit()' ensures it closes.
                client.quit()
