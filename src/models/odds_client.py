import os
import requests
import json
import time
import datetime
import sqlite3
from typing import Dict, Any, Optional

# Load env
from dotenv import load_dotenv
load_dotenv()

class OddsAPIClient:
    """
    The 'Toyota Hilux' of API Clients.
    Robust, cached, and frugal.
    """
    BASE_URL = "https://api.the-odds-api.com/v4/sports"
    CACHE_DURATION = 3600  # 1 hour in seconds
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'bets.db')

    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not found in environment variables.")
        self._init_cache()

    def _get_db(self):
        return sqlite3.connect(self.DB_PATH)

    def _init_cache(self):
        """Initialize the cache table if not exists."""
        with self._get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_cache (
                    key TEXT PRIMARY KEY,
                    response TEXT,
                    timestamp REAL
                )
            """)
            conn.commit()

    def _get_cache_key(self, endpoint: str, params: Dict) -> str:
        """Generate a unique key for the request."""
        # Sort params to ensure consistency
        param_str = json.dumps(params, sort_keys=True)
        return f"{endpoint}:{param_str}"

    def _get_from_cache(self, key: str) -> Optional[Dict]:
        """Retrieve from cache if valid."""
        with self._get_db() as conn:
            cursor = conn.execute("SELECT response, timestamp FROM api_cache WHERE key = ?", (key,))
            row = cursor.fetchone()
            
            if row:
                response_json, timestamp = row
                age = time.time() - timestamp
                if age < self.CACHE_DURATION:
                    print(f"  [CACHE HIT] Using cached data ({int(age)}s old)")
                    return json.loads(response_json)
                else:
                    print(f"  [CACHE STALE] Data is {int(age)}s old (Limit: {self.CACHE_DURATION}s)")
            return None

    def _save_to_cache(self, key: str, data: Any):
        """Save response to cache."""
        with self._get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO api_cache (key, response, timestamp) VALUES (?, ?, ?)",
                (key, json.dumps(data), time.time())
            )
            print("  [CACHE SAVED] Response stored.")

    def _request(self, endpoint: str, params: Dict = {}) -> Any:
        """Internal request method with caching."""
        params['apiKey'] = self.api_key
        cache_key = self._get_cache_key(endpoint, params)
        
        # 1. Check Cache
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data

        # 2. Make Request
        url = f"{self.BASE_URL}/{endpoint}"
        print(f"  [API FETCH] Requesting {url}...")
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            # Check for API usage headers if available
            remaining = resp.headers.get('x-requests-remaining', '?')
            print(f"  [API USAGE] Remaining requests: {remaining}")

            # 3. Save to Cache
            self._save_to_cache(cache_key, data)
            return data

        except requests.exceptions.RequestException as e:
            print(f"  [API ERROR] {e}")
            # If fetch fails, try to return stale cache if it exists?
            # For now, just raise or return None.
            # "Toyota Hilux" principle: Don't crash if possible.
            return None

    def get_odds(self, sport_key: str, regions: str = 'us', markets: str = 'h2h,spreads,totals', odds_format: str = 'american') -> Any:
        """
        Fetch odds for a specific sport.
        Falls back to Action Network (Selenium) if Odds API is exhausted.
        """
        endpoint = f"{sport_key}/odds"
        params = {
            'regions': regions,
            'markets': markets,
            'oddsFormat': odds_format
        }
        
        # 1. Try Primary API
        data = self._request(endpoint, params)
        
        if data is not None:
             return data
             
        # 2. Fallback: Action Network (Selenium)
        print(f"  [FALLBACK] Odds API failed. Engaging Selenium Scraper for {sport_key}...")
        try:
            cache_key = f"selenium:odds:{sport_key}:{datetime.date.today()}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                 print(f"  [CACHE HIT] Using cached Selenium data.")
                 return cached_data

            from src.selenium_client import ActionNetworkSeleniumClient
            scraper = ActionNetworkSeleniumClient()
            fallback_data = scraper.get_odds(sport_key)
            
            if fallback_data:
                print(f"  [FALLBACK SUCCESS] Retrieved {len(fallback_data)} events from Action Network.")
                self._save_to_cache(cache_key, fallback_data)
                return fallback_data
            else:
                return []
        except Exception as e:
            print(f"  [FALLBACK ERROR] {e}")
            return []

    def get_scores(self, sport_key: str, days_from: int = 3) -> Any:
        """
        Fetch scores for a specific sport.
        Falls back to Action Network if Odds API is exhausted.
        """
        endpoint = f"{sport_key}/scores"
        params = {'daysFrom': days_from}
        
        # 1. Try Primary API
        data = self._request(endpoint, params)
        if data is not None:
            return data
            
        # 2. Fallback: Action Network (Selenium)
        print(f"  [FALLBACK] Odds API failed. Engaging Selenium Scraper for scores ({sport_key})...")
        try:
            cache_key = f"selenium:scores:{sport_key}:{datetime.date.today()}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return cached_data

            from src.selenium_client import ActionNetworkSeleniumClient
            scraper = ActionNetworkSeleniumClient()
            fallback_data = scraper.get_odds(sport_key) # Selenium returns combined odds/scores object
            
            if fallback_data:
                self._save_to_cache(cache_key, fallback_data)
                return fallback_data
            return []
        except Exception as e:
            print(f"  [FALLBACK ERROR] {e}")
            return []


    def get_sports(self) -> Any:
        """List available sports."""
        return self._request("")

if __name__ == "__main__":
    # Test Driver
    try:
        client = OddsAPIClient()
        print("Testing OddsAPIClient...")
        
        # Test 2: Get NFL Odds (Example)
        odds = client.get_odds('americanfootball_nfl')
        if odds:
            print(f"Retrieved {len(odds)} NFL games.")
            if len(odds) > 0:
                 print(f"Sample: {odds[0].get('home_team')} vs {odds[0].get('away_team')}")
        else:
            print("Failed to retrieve odds.")

    except Exception as e:
        print(f"Initialization Error: {e}")
