
import time
import os
from .user_driver import UserDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class NeedsHumanAuth(Exception):
    """Raised when DraftKings requires interactive login.

    The caller should update the job status to NEEDS_AUTH and surface this
    to the operator so they can manually log in via the same Chrome profile.
    """


class DraftKingsScraper:
    def __init__(self, profile_path=None):
        self.driver_helper = UserDriver()
        self.profile_path = profile_path

    def scrape(self):
        driver = self.driver_helper.launch(profile_path=self.profile_path)
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
            
            # 6. Scrape: prefer bet cards (avoid pulling entire site nav/footer text)
            bet_texts = []
            selectors = [
                "[data-testid*='bet']",
                "[data-test-id*='bet']",
                "[class*='bet-card']",
                "[class*='BetCard']",
            ]
            for sel in selectors:
                try:
                    for el in driver.find_elements(By.CSS_SELECTOR, sel):
                        try:
                            t = (el.text or '').strip()
                            if t and len(t) > 40:
                                bet_texts.append(t)
                        except Exception:
                            pass
                except Exception:
                    pass

            if bet_texts:
                body_text = "\n\n".join(bet_texts)

                # If we landed on an empty-state / marketing view, don't pretend we scraped bets.
                empty_signals = [
                    "YOUR PICKS WILL SHOW UP HERE",
                    "Select picks to then see",
                    "POPULAR",
                ]
                if any(sig.lower() in body_text.lower() for sig in empty_signals):
                    raise Exception(
                        "DraftKings returned an empty-state page (no settled bets visible). "
                        "Check that the account has settled bets, the correct jurisdiction is selected, "
                        "and the profile is fully logged in."
                    )

                print(f"[DK-Auto] Extracted {len(bet_texts)} bet elements ({len(body_text)} chars).")
                return body_text

            # Fallback: whole page
            body_text = driver.find_element(By.TAG_NAME, "body").text
            print(f"Scraped {len(body_text)} chars (fallback: body text).")
            return body_text

        finally:
            self.driver_helper.close()

    # ------------------------------------------------------------------
    # Automated settled-bets scraper (additive — does not change scrape())
    # ------------------------------------------------------------------

    def scrape_settled_bets_automated(self, include_open: bool = False) -> str:
        """
        Automated wrapper for scraping DraftKings 'My Bets -> Settled' (and optionally 'Open').

        Environment vars consumed:
          DK_PROFILE_PATH    — persistent Chrome profile directory (required)
          DK_SCROLL_PAGES    — number of scroll iterations (default 5)

        Raises:
          NeedsHumanAuth     — if login is required (caller marks job NEEDS_AUTH)

        Returns:
          Body text / bet-card text as a single string for the text parser.
        """
        profile = os.environ.get("DK_PROFILE_PATH") or self.profile_path
        scroll_pages = int(os.environ.get("DK_SCROLL_PAGES", "5"))

        # Create a fresh helper scoped to this call so we don't conflict with scrape()
        helper = UserDriver()
        driver = helper.launch(profile_path=profile)

        keep_open_on_auth = str(os.environ.get('DK_KEEP_OPEN_ON_AUTH', '0')).lower() in ('1','true','yes')
        _skip_close = False

        try:
            # 1. Navigate to My Bets (settled) page
            # DK has multiple routes; the query param tends to land directly on the settled view.
            target_urls = [
                # Prefer the canonical My Bets route first (user reports this works reliably)
                "https://sportsbook.draftkings.com/mybets",
                "https://sportsbook.draftkings.com/my-bets",
                # Some builds support category param; keep as fallback
                "https://sportsbook.draftkings.com/mybets?category=settled",
                "https://sportsbook.draftkings.com/my-bets?category=settled",
            ]
            last_exc = None
            for target_url in target_urls:
                try:
                    print(f"[DK-Auto] Navigating to {target_url}")
                    driver.get(target_url)
                    time.sleep(4)
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    continue
            if last_exc:
                raise last_exc

            # 2. Auth check: detect login wall / location wall
            # If auth/location is required, optionally wait for the operator to complete login
            # in the opened browser (interactive), then continue.
            wait_login_s = int(os.environ.get("DK_WAIT_FOR_LOGIN_SECONDS", "300"))
            # When enabled, keep the worker running and auto-retry within a single job
            # so the operator only has to log in once (no rerun command).
            auto_retry_s = int(os.environ.get("DK_AUTO_RETRY_SECONDS", "0"))

            def _is_login_wall() -> bool:
                try:
                    current_url = (driver.current_url or "").lower()
                    page_src = (driver.page_source or "")
                    # URL signals
                    if any(x in current_url for x in ("log-in", "client-login", "/auth/login", "myaccount.draftkings.com/auth", "code=krn-")):
                        return True
                    # DOM signals
                    if driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
                        return True
                    # Text signals
                    s = page_src.lower()
                    if "to continue to draftkings" in s:
                        return True
                    if "you're not logged in" in s or "you must be logged in" in s:
                        return True
                    if "trouble verifying your location" in s:
                        return True
                    if "remember my email" in s and "password" in s and "log in" in s:
                        return True
                    return False
                except Exception:
                    return False

            if _is_login_wall():
                print("[DK-Auto] Login/location verification required — please complete it in the opened browser window...")
                import time as _time

                # Phase 1: wait_login_s (existing behavior)
                start = _time.time()
                while _time.time() - start < wait_login_s:
                    _time.sleep(3)
                    if not _is_login_wall():
                        print("[DK-Auto] Login appears complete. Continuing...")
                        break

                # Phase 2: optional auto-retry window to avoid forcing a rerun
                if _is_login_wall() and auto_retry_s and auto_retry_s > 0:
                    print(f"[DK-Auto] Still gated. Auto-retrying for up to {auto_retry_s}s (no rerun needed)...")
                    start2 = _time.time()
                    while _time.time() - start2 < auto_retry_s:
                        _time.sleep(3)
                        if not _is_login_wall():
                            print("[DK-Auto] Login appears complete during auto-retry. Continuing...")
                            break

                if _is_login_wall():
                    if keep_open_on_auth:
                        _skip_close = True
                        raise NeedsHumanAuth(
                            f"DraftKings auth/location wall detected (url={driver.current_url!r}). "
                            "Browser left open because DK_KEEP_OPEN_ON_AUTH=1. "
                            "Please log in/verify location in that window, then rerun the worker."
                        )
                    raise NeedsHumanAuth(
                        f"DraftKings auth/location wall detected (url={driver.current_url!r}). "
                        "Please open Chrome with DK_PROFILE_PATH and log in/verify location, then retry."
                    )

            # After auth clears, reload target page once to ensure the shell rehydrates.
            try:
                driver.get(driver.current_url)
                time.sleep(2)
            except Exception:
                pass

            def _collect_tab_cards(tab_name: str, tab_selectors: list, allow_open: bool = False) -> list[str]:
                clicked = False
                for by, sel in tab_selectors:
                    try:
                        for el in driver.find_elements(by, sel):
                            if el.is_displayed():
                                el.click()
                                clicked = True
                                print(f"[DK-Auto] Clicked '{tab_name}' via {sel}")
                                break
                        if clicked:
                            break
                    except Exception:
                        pass
                if not clicked:
                    print(f"[DK-Auto] '{tab_name}' tab not clicked; proceeding with current view.")
                time.sleep(3)

                last_h = driver.execute_script("return document.body.scrollHeight")
                for i in range(scroll_pages):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1.5)
                    new_h = driver.execute_script("return document.body.scrollHeight")
                    if new_h == last_h:
                        print(f"[DK-Auto] Scroll ({tab_name}) stopped at page {i+1} (no new content).")
                        break
                    last_h = new_h

                try:
                    root = driver.find_element(By.TAG_NAME, "main")
                except Exception:
                    root = driver

                cards: list[str] = []
                seen_cards: set[str] = set()
                card_selectors = [
                    "[data-testid*='bet']",
                    "[data-test-id*='bet']",
                    "[class*='bet-card']",
                    "[class*='BetCard']",
                    "[class*='mybets']",
                    "[class*='my-bets']",
                ]
                for sel in card_selectors:
                    try:
                        elements = root.find_elements(By.CSS_SELECTOR, sel) if hasattr(root, "find_elements") else driver.find_elements(By.CSS_SELECTOR, sel)
                        for el in elements:
                            try:
                                t = (el.text or "").strip()
                                if not t or len(t) <= 60 or t in seen_cards:
                                    continue
                                tl = t.lower()
                                outcome = any(x in tl for x in ("won", "lost", "void", "push", "cashed"))
                                if allow_open:
                                    outcome = outcome or any(x in tl for x in ("open", "to win", "payout", "cash out"))
                                money = ("$" in t) or ("usd" in tl)
                                if outcome and money:
                                    seen_cards.add(t)
                                    cards.append(t)
                            except Exception:
                                pass
                    except Exception:
                        pass
                return cards

            bet_texts: list[str] = []
            if include_open:
                open_selectors = [
                    (By.XPATH, "//button[normalize-space()='Open']"),
                    (By.XPATH, "//a[normalize-space()='Open']"),
                    (By.XPATH, "//*[@data-testid='open-tab']"),
                    (By.XPATH, "//div[normalize-space()='Open']"),
                    (By.XPATH, "//span[normalize-space()='Open']"),
                ]
                bet_texts.extend(_collect_tab_cards("Open", open_selectors, allow_open=True))

            settled_selectors = [
                (By.XPATH, "//button[normalize-space()='Settled']"),
                (By.XPATH, "//a[normalize-space()='Settled']"),
                (By.XPATH, "//*[@data-testid='settled-tab']"),
                (By.XPATH, "//*[contains(@class,'settled') and (self::button or self::a)]"),
                (By.XPATH, "//div[normalize-space()='Settled']"),
                (By.XPATH, "//span[normalize-space()='Settled']"),
            ]
            bet_texts.extend(_collect_tab_cards("Settled", settled_selectors, allow_open=False))

            if bet_texts:
                body = "\n\n".join(bet_texts)
                print(f"[DK-Auto] Extracted {len(bet_texts)} bet-card candidates ({len(body)} chars).")
                return body

            # Fallback: raw body text
            body = driver.find_element(By.TAG_NAME, "body").text
            # If we still look like we're gated, treat as auth required.
            b_low = (body or '').lower()
            if any(x in b_low for x in ("you're not logged in", "you must be logged in", "trouble verifying your location")):
                if keep_open_on_auth:
                    _skip_close = True
                raise NeedsHumanAuth(
                    f"DraftKings gated view detected (url={driver.current_url!r}). "
                    "Please log in/verify location and retry."
                )
            print(f"[DK-Auto] Fallback body text ({len(body)} chars). url={driver.current_url!r}")
            return body

        finally:
            if _skip_close:
                print("[DK-Auto] Leaving browser open for manual login (DK_KEEP_OPEN_ON_AUTH=1).")
            else:
                helper.close()

