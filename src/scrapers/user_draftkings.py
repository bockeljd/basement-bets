
import time
from .user_driver import UserDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class DraftKingsScraper:
    def __init__(self):
        self.driver_helper = UserDriver()

    def scrape(self):
        driver = self.driver_helper.launch()
        try:
            # 1. Navigate to DK Sportsbook Home
            print("Navigating to DraftKings...")
            driver.get("https://sportsbook.draftkings.com/")
            time.sleep(3)
            
            # 2. Check Login Status
            print("Checking login status...")
            page_source = driver.page_source
            
            # If "Log In" or "Sign Up" buttons are prominent, user needs to log in
            if "Log In" in page_source and "Sign Up" in page_source:
                print(">>> Please Log In to DraftKings in the browser window <<<")
                logged_in = False
                start = time.time()
                while time.time() - start < 300: # 5 mins
                    time.sleep(3)
                    page_source = driver.page_source
                    # Check for signs of login (username, balance, etc)
                    if "BALANCE" in page_source or "My Bets" in page_source:
                        logged_in = True
                        break
                    # Check URL - if no longer on login page
                    if "log-in" not in driver.current_url and "client-login" not in driver.current_url:
                        if "BALANCE" in driver.page_source or "My Bets" in driver.page_source:
                            logged_in = True
                            break
                
                if not logged_in:
                    raise Exception("Login timeout")
            
            print("Login confirmed! Navigating to My Bets...")
            time.sleep(2)
            
            # 3. Click "My Bets" link in navigation
            try:
                # Try finding "My Bets" link in the page
                my_bets_link = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.LINK_TEXT, "My Bets"))
                )
                my_bets_link.click()
                print("Clicked 'My Bets' link!")
            except:
                print("Could not find 'My Bets' link. Trying XPath...")
                try:
                    my_bets = driver.find_element(By.XPATH, "//a[contains(text(), 'My Bets')]")
                    my_bets.click()
                except:
                    print("Fallback: Trying to find via href...")
                    try:
                        my_bets = driver.find_element(By.CSS_SELECTOR, "a[href*='mybets'], a[href*='my-bets']")
                        my_bets.click()
                    except:
                        # Fallback 2: Direct URL
                         print("Fallback Navigation 2: Direct URL...")
                         driver.get("https://sportsbook.draftkings.com/my-bets")
            
            time.sleep(5)
            
            # Check if we are in a "drawer" (Bet Slip) or full page
            # If full page, we should see "Open", "Settled", "Won", "Lost" tabs.
            
            # 4. Click "Settled" tab
            print("Looking for 'Settled' tab...")
            settled_clicked = False
            # Try multiple selectors for Settled
            settled_selectors = [
                (By.XPATH, "//button[contains(text(), 'Settled')]"),
                (By.XPATH, "//a[contains(text(), 'Settled')]"),
                (By.XPATH, "//*[@data-testid='settled-tab']"),
                (By.XPATH, "//div[contains(text(), 'Settled')]"), # Sometimes just text in a div tab
                (By.XPATH, "//span[contains(text(), 'Settled')]"),
            ]
            for by, selector in settled_selectors:
                try:
                    elements = driver.find_elements(by, selector)
                    for el in elements:
                        if el.is_displayed():
                            # Ensure it's not "Settled Date" sort header, but a tab
                            el.click()
                            settled_clicked = True
                            print(f"Clicked 'Settled' tab using {selector}!")
                            break
                    if settled_clicked:
                        break
                except:
                    pass
            
            if not settled_clicked:
                print("Could not find Settled tab via click. Logic will try to scroll anyway...")
            
            time.sleep(5)  # Wait for bets to load
            
            # 5. Wait for bet cards to appear
            print("Waiting for bet cards to load...")
            bet_content_found = False
            for _ in range(10):
                page_text = driver.page_source
                # Look for bet indicators like "Parlay", "Straight", "$", "Won", "Lost", etc.
                if any(x in page_text for x in ["bet-card", "data-bet", "Won", "Lost", "Void", "Graded"]):
                    bet_content_found = True
                    break
                time.sleep(2)
            
            if not bet_content_found:
                print("Warning: Bet cards may not have loaded fully.")
            
            # 6. Scroll to load more bets
            print("Scrolling to load more bets...")
            last_height = driver.execute_script("return document.body.scrollHeight")
            for _ in range(5):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            
            # 6. Scrape the page
            body_text = driver.find_element(By.TAG_NAME, "body").text
            print(f"Scraped {len(body_text)} chars.")
            return body_text

        finally:
            self.driver_helper.close()

