
import time
from .user_driver import UserDriver
from selenium.webdriver.common.by import By

class FanDuelScraper:
    def __init__(self):
        self.driver_helper = UserDriver()

    def scrape(self):
        # Use PROJECT-LOCAL Chrome profile (persists cookies, no conflicts with system Chrome)
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        profile_path = os.path.join(base_dir, "chrome_profile_fd")
        
        # Create the directory if it doesn't exist
        os.makedirs(profile_path, exist_ok=True)
        
        print(f"[FanDuel] Using dedicated profile: {profile_path}")
        print("[FanDuel] First time: You'll need to log in. After that, cookies are saved!")
        
        driver = self.driver_helper.launch(profile_path=profile_path)
        try:
            # 1. Navigate to FanDuel (Ohio optimized)
            # Generic: https://sportsbook.fanduel.com/
            # Ohio: https://oh.sportsbook.fanduel.com/
            driver.get("https://oh.sportsbook.fanduel.com/")
            
            print("Please Log In to FanDuel in the opened window.")
            print("If you see 'Press & Hold', please solve it.")
            
            # 2. Wait for Login
            logged_in = False
            start = time.time()
            while time.time() - start < 300: # 5 mins
                curr = driver.current_url
                src = driver.page_source
                
                # captcha check
                if "Press & Hold" in src or "human" in src.lower() and "confirm" in src.lower():
                    # Still stuck in captcha
                    time.sleep(1)
                    continue

                if "fanduel.com" in curr and "login" not in curr and "account" in curr:
                     # Stronger check: "account" or strict sportsbook home
                     # But homepage might not have "account".
                     # If user is at "https://oh.sportsbook.fanduel.com/", they are logged in IF "Log In" button is gone.
                     # But that requires element check.
                     # Let's rely on user navigating to history logic?
                     # Or just wait for url to contain "account"?
                     logged_in = True
                     break
                     
                # Fallback: if user navigates to sports/nfl, we assume logged in?
                if "sportsbook.fanduel.com" in curr and "login" not in curr and "Press & Hold" not in src:
                    # Check for "My Bets" or "Account" text in body?
                    if "My Bets" in src or "Account" in src:
                        logged_in = True
                        break
                        
                time.sleep(1)
            
            if not logged_in:
                raise Exception("Login timeout")
                
            print("Login detected.")
            # 3. Go to History (Click based)
            print("Navigating to History (UI Click Path)...")
            driver.get("https://oh.sportsbook.fanduel.com/")
            time.sleep(5)
            
            # Click "My Bets"
            try:
                # Try explicit "My Bets" text (header or nav)
                # Usually in a pill or footer.
                # Let's search for any element with exact text "My Bets"
                my_bets_btn = None
                elements = driver.find_elements(By.XPATH, "//*[text()='My Bets']")
                for el in elements:
                    if el.is_displayed():
                        my_bets_btn = el
                        break
                
                if my_bets_btn:
                    print("Clicking 'My Bets'...")
                    my_bets_btn.click()
                    time.sleep(3)
                else:
                    print("Could not find 'My Bets' button. Trying URL fallback...")
                    driver.get("https://sportsbook.fanduel.com/bettings-activity/settled")
                    
            except Exception as e:
                print(f"Nav Error: {e}")
                driver.get("https://sportsbook.fanduel.com/bettings-activity/settled")

            time.sleep(5)
            
            # Click "Settled" if visible
            try:
                settled_btn = driver.find_element(By.XPATH, "//*[text()='Settled']")
                if settled_btn.is_displayed():
                    print("Clicking 'Settled' tab...")
                    settled_btn.click()
                    time.sleep(3)
            except:
                pass # Already there?
            
            # Dismiss location popup if present
            print("Checking for location popup...")
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.common.action_chains import ActionChains
            
            try:
                # 1. Try ESC key to dismiss modal
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(1)
                
                # 2. Look for close/X buttons on modals (various patterns)
                close_selectors = [
                    "//button[contains(@aria-label, 'close') or contains(@aria-label, 'Close')]",
                    "//button[contains(@class, 'close')]",
                    "//*[contains(@class, 'modal-close')]",
                    "//button[text()='×' or text()='X' or text()='x']",
                    "//*[@data-testid='close-button']",
                    "//div[contains(@class, 'overlay')]//button",
                ]
                for selector in close_selectors:
                    try:
                        buttons = driver.find_elements(By.XPATH, selector)
                        for btn in buttons:
                            if btn.is_displayed():
                                print(f"Clicking close button...")
                                btn.click()
                                time.sleep(1)
                    except:
                        pass
                
                # 3. Try JavaScript to remove overlay/modal elements
                driver.execute_script("""
                    // Remove location modals by class patterns
                    document.querySelectorAll('[class*="modal"], [class*="overlay"], [class*="popup"]').forEach(el => {
                        if (el.innerText && el.innerText.includes('location')) {
                            el.style.display = 'none';
                        }
                    });
                    // Click any backdrop
                    document.querySelectorAll('[class*="backdrop"]').forEach(el => el.click());
                """)
                time.sleep(1)
                
                # 4. Press ESC again
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(1)
                        
            except Exception as e:
                print(f"Modal dismiss error: {e}")
            
            time.sleep(2)
            
            # 3. Wait for History Table
            start_wait = time.time()
            table_found = False
            while time.time() - start_wait < 60:
                src = driver.page_source
                if "Settled" in src and ("Date" in src or "Selection" in src or "Stake" in src or "Wager" in src):
                    table_found = True
                    break
                # Also check for captcha
                if "Press & Hold" in src:
                    print("Captcha detected! Waiting...")
                time.sleep(1)
                
            if not table_found:
                 print("Warning: Table not found implicitly. Trying fallback wait...")
                 time.sleep(5)
            
            print("History table loaded.")
            
            print("History table detected! Scraping...")
            time.sleep(2) # Allow render
            
            # 3.5. Scroll to Load More (Infinite Scroll)
            print("Scrolling to load more bets...")
            last_height = driver.execute_script("return document.body.scrollHeight")
            for _ in range(5): # Scroll 5 times
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            
            # Scroll back to top just in case
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            # 4. Scrape
            # Grab body text
            body_text = driver.find_element(By.TAG_NAME, "body").text
            print(f"Scraped {len(body_text)} chars.")
            return body_text

        finally:
            self.driver_helper.close()
