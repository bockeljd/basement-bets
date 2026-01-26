
import sys
import os

# Ensure src is in path
sys.path.append(os.getcwd())

from src.selenium_client import SeleniumClient

def reproduce():
    print("--- Reproducing Selenium Error ---")
    try:
        # Use simple dot-path to match app usage, or absolute to be sure
        client = SeleniumClient(headless=False, profile_path="./chrome_profile")
        print("Success!")
        client.quit()
    except Exception as e:
        print(f"\nCaught Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reproduce()
