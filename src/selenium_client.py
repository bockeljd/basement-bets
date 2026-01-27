
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import undetected_chromedriver as uc
import os
import time
import logging
import shutil
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class SeleniumClient:
    def _detect_chrome_binary(self):
        # Common macOS locations
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        # Try PATH
        for exe in ("google-chrome", "chromium", "chromium-browser", "brave", "msedge"):
            w = shutil.which(exe)
            if w:
                return w
        return None

    def __init__(self, headless=False, profile_path=None, browser_executable_path=None):
        self.options = uc.ChromeOptions()

        # Ensure Chrome binary location is a string (undetected_chromedriver can choke on Path/None)
        if browser_executable_path is None:
            browser_executable_path = self._detect_chrome_binary()
        if browser_executable_path is None:
            # Avoid undetected_chromedriver trying to set a non-string binary_location.
            raise RuntimeError(
                "No Chrome/Chromium browser detected. Install Google Chrome (recommended) and retry. "
                "Expected at /Applications/Google Chrome.app/..."
            )

        # Ensure it's always a string
        self.options.binary_location = str(browser_executable_path)
        self.browser_executable_path = str(browser_executable_path)

        # 1. Force "Allow" for Geolocation
        prefs = {
            "profile.default_content_setting_values.geolocation": 1,
            "profile.default_content_setting_values.notifications": 2,
            "google.geolocation.access_enabled": True
        }
        self.options.add_experimental_option("prefs", prefs)

        # 2. Persistent Profile
        if profile_path:
            self.options.add_argument(f"--user-data-dir={os.path.abspath(profile_path)}")

        # 3. Initialize Driver
        try:
            # use_subprocess=True helps avoid some lockfile issues
            self.driver = uc.Chrome(
                options=self.options,
                use_subprocess=True,
                headless=headless,
                browser_executable_path=self.browser_executable_path,
            )
        except Exception as e:
            print(f"Failed to initialize undetected_chromedriver: {e}")
            if not self.browser_executable_path:
                print("[SeleniumClient] No Chrome/Chromium binary detected. Install Google Chrome or Chromium and retry.")
            raise e
            
    def quit(self):
        if self.driver:
            self.driver.quit()

    def scrape_draftkings_bets(self):
        """
        Navigates to DraftKings Settled Bets.
        Waits for manual login if needed.
        """
        try:
            target_url = "https://sportsbook.draftkings.com/mybets?category=settled"
            
            # 1. Initial Navigation
            logging.info(f"Navigating to {target_url}...")
            self.driver.get(target_url)
            time.sleep(5)

            # 2. Robust Navigation Loop (Login / Download Interstitial Bypass)
            # We loop until we confirm we are on the actual betting page
            max_retries = 24 # 2 minutes total wait
            for attempt in range(max_retries):
                current_url = self.driver.current_url
                page_source = self.driver.page_source
                
                # Case A: Interstitial (Download App / Geo)
                if "Download the DraftKings Sportsbook App" in page_source or "Confirm Location" in self.driver.title:
                    print(f"🔄 [Attempt {attempt+1}] Interstitial Page Detected. Refreshing...")
                    self.driver.refresh()
                    time.sleep(5)
                    continue
                    
                # Case B: Login Page
                if "log-in" in current_url or "client-login" in current_url or "Log In" in page_source:
                    print(f"🚨 [Attempt {attempt+1}] Login Required. Waiting for user input...")
                    # Allow user time to log in
                    time.sleep(5)
                    continue

                # Case C: Success (My Bets / Settled)
                if "mybets" in current_url or "My Bets" in page_source or "Settled Date" in page_source:
                    print("✅ Successfully landed on My Bets page!")
                    break
                
                print(f"⏳ [Attempt {attempt+1}] Waiting for page load... ({current_url})")
                time.sleep(3)
            
            # 3. Pagination (Show More)
            try:
                for _ in range(5): 
                    load_more = self.driver.find_element(By.XPATH, "//div[contains(text(), 'Show More')]")
                    if load_more and load_more.is_displayed():
                        self.driver.execute_script("arguments[0].click();", load_more)
                        time.sleep(3)
                    else:
                        break
            except:
                pass 

            # 4. Wait for Content
            print("👀 Waiting for bet cards...")
            try:
                WebDriverWait(self.driver, 15).until(
                    lambda d: "Won" in d.page_source or "Lost" in d.page_source or "bet-card" in d.page_source or "Settled Date" in d.page_source
                )
                print("✅ Bet content detected!")
            except:
                print("⚠️ Warning: specific bet content (Won/Lost) not detected. Scraping anyway...")

            # 5. Extract
            return self.driver.page_source

        except Exception as e:
            logging.error(f"DK Scrape Error: {e}")
            return None

