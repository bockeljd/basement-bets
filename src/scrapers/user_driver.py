
import time
from src.selenium_client import SeleniumDriverFactory
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

class UserDriver:
    def __init__(self):
        self.driver = None

    def launch(self, profile_path=None):
        """
        Launches a visible browser using undetected-chromedriver.
        If profile_path is provided, uses that directory for persistent session (cookies, etc).
        """
        print(f"[UserDriver] Launching visible browser (Undetected Mode)... Profile: {profile_path or 'Temp'}")
        
        try:
            import ssl
            ssl._create_default_https_context = ssl._create_unverified_context
            import undetected_chromedriver as uc
            
            options = uc.ChromeOptions()
            if profile_path:
                options.add_argument(f"--user-data-dir={profile_path}")
            
            # Grant geolocation permission
            prefs = {
                "profile.default_content_setting_values.geolocation": 1
            }
            options.add_experimental_option("prefs", prefs)
            
            # Using subprocess=True is safer for UC
            # Pin browser binary if available (avoids "Binary Location Must be a String")
            browser_bin = None
            for p in [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            ]:
                if os.path.exists(p):
                    browser_bin = p
                    break
            self.driver = uc.Chrome(options=options, use_subprocess=True, browser_executable_path=browser_bin)
            self.driver.maximize_window()
            
            return self.driver
        except Exception as e:
            print(f"[UserDriver] Failed to launch undetected driver: {e}")
            raise e

    def wait_for_login(self, success_url_fragment: str, timeout: int = 180):
        """
        Waits for the user to log in by checking the URL or a specific element.
        """
        print(f"[UserDriver] Waiting {timeout}s for user to log in (Fragment: {success_url_fragment})...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                current_url = self.driver.current_url
                if success_url_fragment in current_url:
                    print("[UserDriver] Login detected via URL!")
                    return True
            except:
                pass
            time.sleep(1)
            
        print("[UserDriver] Login timeout reached.")
        return False

    def close(self):
        if self.driver:
            self.driver.quit()
