import os
import requests
import json
import time
import datetime
from typing import Dict, Any, Optional

from src.database import get_db_connection, _exec  # Use shared DB logic

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
    
    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")
        # In Vercel, we might not want to raise error immediately if key missing?
        # But user wants authentication.
        if not self.api_key:
             print("[WARN] ODDS_API_KEY not found.")
        
        # We generally don't want to run DDL at runtime in Serverless if possible, 
        # but for now we try to init cache table safely.
        self._init_cache()

    def _init_cache(self):
        """Initialize the cache table if not exists."""
        # Use generic connection (SQLite or PG)
        # TEXT/REAL types are compatible.
        query = """
            CREATE TABLE IF NOT EXISTS api_cache (
                key TEXT PRIMARY KEY,
                response TEXT,
                timestamp REAL
            )
        """
        try:
            with get_db_connection() as conn:
                _exec(conn, query)
                conn.commit()
        except Exception as e:
            print(f"[OddsAPI] Cache Init Failed (Non-Fatal): {e}")

    def _get_cache_key(self, endpoint: str, params: Dict) -> str:
        """Generate a unique key for the request."""
        # Sort params to ensure consistency
        param_str = json.dumps(params, sort_keys=True)
        return f"{endpoint}:{param_str}"

    def _get_from_cache(self, key: str) -> Optional[Dict]:
        """Retrieve from cache if valid."""
        query = "SELECT response, timestamp FROM api_cache WHERE key = ?"
        try:
            with get_db_connection() as conn:
                cursor = _exec(conn, query, (key,))
                row = cursor.fetchone()
                
                if row:
                    # DictCursor vs Tuple access
                    # SQLite Row vs PG DictRow. Both support key access?
                    # Row supports integer index. DictRow supports key.
                    # Let's verify what _exec returns.
                    # It returns cursor.
                    # SQLite row works like tuple too? Yes.
                    # Postgres DictCursor works like list/tuple? Yes.
                    
                    response_json = row[0]
                    timestamp = row[1]
                    
                    age = time.time() - timestamp
                    if age < self.CACHE_DURATION:
                        print(f"  [CACHE HIT] Using cached data ({int(age)}s old)")
                        return json.loads(response_json)
                    else:
                        print(f"  [CACHE STALE] Data is {int(age)}s old")
        except Exception as e:
             print(f"[OddsAPI] Cache Read Error: {e}")
        return None

    def _save_to_cache(self, key: str, data: Any):
        """Save response to cache."""
        # SQLite: INSERT OR REPLACE
        # Postgres: INSERT ... ON CONFLICT
        # _exec handles "INSERT OR IGNORE". 
        # But here we want REPLACE/UPDATE.
        # "INSERT OR REPLACE" is valid in SQLite.
        # Postgres uses "INSERT ... ON CONFLICT (key) DO UPDATE SET ..."
        
        # Simpler approach: DELETE then INSERT (Atomic enough for cache)
        # OR handle DB specific syntax here.
        # Let's rely on DELETE + INSERT for simplicity across both.
        
        del_query = "DELETE FROM api_cache WHERE key = ?"
        ins_query = "INSERT INTO api_cache (key, response, timestamp) VALUES (?, ?, ?)"
        
        try:
            with get_db_connection() as conn:
                _exec(conn, del_query, (key,))
                _exec(conn, ins_query, (key, json.dumps(data), time.time()))
                conn.commit()
                print("  [CACHE SAVED] Response stored.")
        except Exception as e:
            print(f"[OddsAPI] Cache Write Error: {e}")

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
             
        # 2. Fallback: Action Network (API)
        print(f"  [FALLBACK] Odds API failed. Engaging Action Network (API) for {sport_key}...")
        try:
            cache_key = f"action:odds:{sport_key}:{datetime.date.today()}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                 print(f"  [CACHE HIT] Using cached Action Network data.")
                 return cached_data

            from src.action_network import ActionNetworkClient
            scraper = ActionNetworkClient()
            fallback_data = scraper.fetch_odds(sport_key)
            
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
            
        # 2. Fallback: Action Network (API)
        print(f"  [FALLBACK] Odds API failed. Engaging Action Network (API) for scores ({sport_key})...")
        try:
            cache_key = f"action:scores:{sport_key}:{datetime.date.today()}:{days_from}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                print("  [CACHE HIT] Using cached Action Network scores.")
                return cached_data

            from src.action_network import ActionNetworkClient
            scraper = ActionNetworkClient()
            
            # Generate list of dates for the last N days
            date_list = []
            today = datetime.date.today()
            for i in range(days_from + 1): 
                d = today - datetime.timedelta(days=i)
                date_list.append(d.strftime('%Y%m%d'))
            
            # fetch_odds returns full event objects which include scores/status
            fallback_data = scraper.fetch_odds(sport_key, date_list) 
            
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
