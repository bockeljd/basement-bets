import requests
import os
import sys

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from src.ingestion_engine import IngestionEngine
except ImportError:
    from ingestion_engine import IngestionEngine

class EplClient(IngestionEngine):
    """
    Client for football-data.org (EPL).
    """
    BASE_URL = "http://api.football-data.org/v4"
    
    def __init__(self, api_key=None):
        super().__init__()
        self.api_key = api_key or os.getenv("FOOTBALL_DATA_API_KEY")
        if not self.api_key:
            print("[EPL] Warning: FOOTBALL_DATA_API_KEY not set.")

    def fetch_teams(self):
        """
        Fetch all teams for Premier League (PL).
        """
        if not self.api_key: return []
        
        url = f"{self.BASE_URL}/competitions/PL/teams"
        headers = {"X-Auth-Token": self.api_key}
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            # Ingest Snapshot
            self.ingest_data("FOOTBALL_DATA", "EPL", data, target_date="SEEDS")
            
            return data.get('teams', [])
        except Exception as e:
            print(f"[EPL] Error fetching teams: {e}")
            return []

if __name__ == "__main__":
    client = EplClient()
    teams = client.fetch_teams()
    print(f"Fetched {len(teams)} EPL teams.")
