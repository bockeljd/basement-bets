from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time
import os

class SeleniumDriverFactory:
    """
    Factory to create configured Chrome drivers for scraping.
    """
    
    @staticmethod
    def create_driver(headless=True):
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Suppress logging
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        # Try to find chromedriver in env or path
        # Assuming chromedriver is in path for now as per previous successful selenium runs in this workspace
        try:
            driver = webdriver.Chrome(options=options)
            return driver
        except Exception as e:
            print(f"[SELENIUM] Failed to init driver: {e}")
            return None
