
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.selenium_client import SeleniumClient
# Use specific DK parser for bulk history
from src.parsers.draftkings_text import DraftKingsTextParser
from bs4 import BeautifulSoup

# Use the SAME profile folder as FanDuel to centralize your "digital identity"
PROFILE_DIR = "./chrome_profile"

def run():
    print("🚀 Launching DraftKings Scraper...")
    
    # Initialize client with persistent profile
    # Ensure profile dir exists
    if not os.path.exists(PROFILE_DIR):
        os.makedirs(PROFILE_DIR)
        
    client = SeleniumClient(headless=False, profile_path=PROFILE_DIR)
    
    try:
        html = client.scrape_draftkings_bets()
        
        if not html:
            print("❌ Failed to get data.")
            return
            
        print("✅ HTML Retrieved. Converting to Text...")
        
        # 1. Clean HTML to Text
        soup = BeautifulSoup(html, "html.parser")
        
        # DraftKings bets are usually in cards. We try to grab the main container.
        bet_container = soup.find("div", {"class": "my-bets-pane"})
        
        if bet_container:
            raw_text = bet_container.get_text(separator="\n", strip=True)
        else:
            # Fallback: Dump everything
            raw_text = soup.get_text(separator="\n", strip=True)
            
        # DEBUG: Save content
        with open("debug_dk.html", "w") as f:
            f.write(html)
        with open("debug_dk.txt", "w") as f:
            f.write(raw_text)
            
        print(f"📝 Raw Text Preview: {raw_text[:200]}...")

        # 2. Parse with DK Parser
        print("🤖 Parsing bets with DraftKingsTextParser...")
        parser = DraftKingsTextParser()
        bets = parser.parse(raw_text)
        
        # 3. Output
        print(f"💰 Found {len(bets)} bets:")
        for bet in bets:
             print(f" - {bet.get('date')} | {bet.get('selection')} | {bet.get('wager')} -> {bet.get('payout')}") # keys differ from LLM parser

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("\n" + "="*40)
        input("🛑 Script finished. Press ENTER to close Chrome...")
        client.quit()



if __name__ == "__main__":
    run()
