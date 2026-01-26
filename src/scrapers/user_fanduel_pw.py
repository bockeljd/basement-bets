
import os
import time
from playwright.sync_api import sync_playwright

class FanDuelScraperPW:
    def __init__(self):
        pass

    def scrape(self):
        # Use a persistent context for cookies + session
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        user_data_dir = os.path.join(base_dir, "playwright_profile_fd")
        
        print(f"[FanDuel PW] Launching Playwright with profile: {user_data_dir}")
        
        with sync_playwright() as p:
            # Launch persistent context
            browser_type = p.chromium
            
            context = browser_type.launch_persistent_context(
                user_data_dir,
                headless=False,
                channel="chrome",
                viewport={"width": 1280, "height": 720},
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
            )
            
            page = context.pages[0] if context.pages else context.new_page()
            
            # Stealth scripts
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            try:
                print("Navigating to FanDuel (Ohio)...")
                page.goto("https://oh.sportsbook.fanduel.com/", timeout=60000)
                
                # Check if logged in - need to look for ACTUAL login indicators
                # NOT "My Bets" (visible when logged out too)
                # Look for: username display, account balance, or absence of "Log in" button
                print("Checking login status...")
                print(">>> If not logged in, please log in now in the browser window <<<")
                logged_in = False
                start = time.time()
                
                while time.time() - start < 300: # 5 mins max wait
                    page.wait_for_timeout(3000)
                    
                    # Get page text to check for login indicators
                    try:
                        page_text = page.locator("body").inner_text()
                    except:
                        page_text = ""
                    
                    # If "Log in" and "Join now" are visible, user is NOT logged in
                    if "Log in" in page_text and "Join now" in page_text:
                        print("Not logged in yet... waiting for you to complete login...")
                        continue
                    
                    # If we DON'T see "Log in" button text, user might be logged in
                    # Also look for balance indicator (often shows as $XXX.XX)
                    if "Log in" not in page_text:
                        # Additional check: Try clicking My Bets and see if we get bet content
                        try:
                            page.get_by_role("link", name="My Bets").click()
                            page.wait_for_timeout(3000)
                            
                            # Check if we're on a bets page with actual content
                            new_text = page.locator("body").inner_text()
                            if "Settled" in new_text and ("Open" in new_text or "Pending" in new_text):
                                logged_in = True
                                print("Login confirmed! Reached My Bets page.")
                                break
                            elif "Log in" in new_text or "Sign in" in new_text:
                                # Got redirected to login
                                print("Redirected to login page. Please log in...")
                                page.goto("https://oh.sportsbook.fanduel.com/", timeout=30000)
                                continue
                        except:
                            pass
                    
                    page.wait_for_timeout(2000)
                
                if not logged_in:
                    print("WARNING: Login timeout. Proceeding anyway...")
                
                # Click on "My Bets" to navigate
                print("Clicking 'My Bets'...")
                try:
                    page.get_by_role("link", name="My Bets").click()
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"Could not click My Bets: {e}")
                    # Fallback to direct URL (Ohio specific)
                    page.goto("https://oh.sportsbook.fanduel.com/bettings-activity/settled", timeout=30000)
                
                # Click "Settled" tab
                print("Looking for 'Settled' tab...")
                try:
                    settled_tab = page.get_by_role("tab", name="Settled")
                    if settled_tab.is_visible():
                        settled_tab.click()
                        page.wait_for_timeout(3000)
                except:
                    print("Could not find Settled tab, trying text click...")
                    try:
                        page.locator("text=Settled").first.click()
                        page.wait_for_timeout(3000)
                    except:
                        pass
                
                # Wait for bets to load
                print("Waiting for bets to load...")
                page.wait_for_timeout(5000)
                
                # Scroll to load more
                print("Scrolling to load more bets...")
                for _ in range(5):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)
                
                # Scrape
                text = page.locator("body").inner_text()
                print(f"[PW] Scraped {len(text)} chars.")
                return text
                
            except Exception as e:
                print(f"[PW] Error: {e}")
                raise e
            finally:
                context.close()
