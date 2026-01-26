
import sys
import os
import time

# Ensure we can import from src
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.scrapers.user_driver import UserDriver

PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile")

def init_profile():
    print("------------------------------------------------")
    print("   BROWSER PROFILE SETUP (ONE-TIME LOGIN)")
    print("------------------------------------------------")
    print(f"Profile Path: {PROFILE_DIR}")
    print("1. A Chrome window will open.")
    print("2. Please LOG IN to FanDuel (and check 'Remember Me').")
    print("3. Solve any Captchas manually.")
    print("4. Once you are logged in and see your account, close the browser manually or wait.")
    print("------------------------------------------------")
    
    driver_helper = UserDriver()
    try:
        driver = driver_helper.launch(profile_path=PROFILE_DIR)
        driver.get("https://oh.sportsbook.fanduel.com/")
        
        print("Browser launched. Waiting for you to login...")
        # Keep alive for 5 minutes so user can login comfortably
        time.sleep(300) 
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Closing setup session.")
        # If user closed it manually, this might error, expected.
        try:
            driver_helper.close()
        except:
            pass

if __name__ == "__main__":
    init_profile()
