import requests
import time
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional
import sys

# Adjust imports based on project structure
try:
    from src.database import upsert_event, upsert_event_provider, upsert_game_result, log_ingestion_run, get_db_connection, _exec
except ImportError:
    # Fallback for running as script
    from database import upsert_event, upsert_event_provider, upsert_game_result, log_ingestion_run, get_db_connection, _exec

class FootballDataClient:
    BASE_URL = "https://api.football-data.org/v4"
    EPL_COMPETITION_ID = "PL" # Premier League

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY")
        if not self.api_key:
            print("[FootballDataClient] GENERIC WARNING: No API Key provided. Calls will likely fail 403.")
            
        self.session = requests.Session()
        self.session.headers.update({
            'X-Auth-Token': self.api_key,
            'User-Agent': 'BasementBets/1.0'
        })
        self._last_request_time = 0
        # Free Tier: 10 req / minute -> 1 req / 6 seconds. Let's start with 6.5s delay to be safe.
        self._rate_limit_delay = 6.5 

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            wait_time = self._rate_limit_delay - elapsed
            print(f"[FootballDataClient] Rate limiting... sleeping {wait_time:.2f}s")
            time.sleep(wait_time)
        self._last_request_time = time.time()

    def fetch_matches(self, date_from: str, date_to: str) -> List[Dict]:
        """
        Fetch matches for EPL within date range (YYYY-MM-DD).
        """
        url = f"{self.BASE_URL}/competitions/{self.EPL_COMPETITION_ID}/matches"
        params = {
            'dateFrom': date_from,
            'dateTo': date_to
        }
        
        self._rate_limit()
        try:
            resp = self.session.get(url, params=params, timeout=10)
            
            if resp.status_code == 429:
                print("[FootballDataClient] Hit 429 Rate Limit. Backing off for 60s...")
                time.sleep(60)
                return self.fetch_matches(date_from, date_to) # Retry once
                
            resp.raise_for_status()
            data = resp.json()
            return data.get('matches', [])
        except Exception as e:
            print(f"[FootballDataClient] Error fetching fixtures: {e}")
            return []

    def ingest_epl(self, date_from: str, date_to: str):
        """
        Orchestrator to ingest EPL data.
        """
        print(f"[FootballDataClient] Ingesting EPL from {date_from} to {date_to}...")
        matches = self.fetch_matches(date_from, date_to)
        
        count = 0
        for m in matches:
            try:
                # Parse
                provider_id = str(m.get('id'))
                utc_date = m.get('utcDate') # 2024-01-30T19:30:00Z
                status_raw = m.get('status')
                
                home_name = m.get('homeTeam', {}).get('name')
                away_name = m.get('awayTeam', {}).get('name')
                
                # Scores
                full_time = m.get('score', {}).get('fullTime', {})
                h_score = full_time.get('home')
                a_score = full_time.get('away')
                
                # Normalize Status
                final = False
                status = 'scheduled'
                if status_raw == 'FINISHED':
                    status = 'final'
                    final = True
                elif status_raw in ['IN_PLAY', 'PAUSED']:
                    status = 'in_progress'
                elif status_raw == 'POSTPONED':
                    status = 'postponed'
                
                # 1. Resolve or Create Canonical ID
                canonical_id = self._resolve_event_id(provider_id)
                if not canonical_id:
                    canonical_id = str(uuid.uuid4())

                # 2. Upsert Event
                # Parse date
                dt = None
                if utc_date:
                    try:
                        dt = datetime.strptime(utc_date, "%Y-%m-%dT%H:%M:%SZ")
                    except:
                        pass
                        
                event_rec = {
                    "id": canonical_id,
                    "league": "EPL",
                    "start_time": dt,
                    "home_team": home_name,
                    "away_team": away_name,
                    "status": status
                }
                upsert_event(event_rec)
                
                # 3. Upsert Provider Map
                mapping_rec = {
                    "event_id": canonical_id,
                    "provider": "football_data",
                    "provider_event_id": provider_id
                }
                upsert_event_provider(mapping_rec)
                
                # 4. Upsert Result
                if h_score is not None and a_score is not None:
                     res_rec = {
                         "event_id": canonical_id,
                         "home_score": h_score,
                         "away_score": a_score,
                         "final_flag": final
                     }
                     upsert_game_result(res_rec)
                
                count += 1
            except Exception as ex:
                print(f"[FootballDataClient] Error processing match {m.get('id')}: {ex}")

        # Log
        log_ingestion_run({
            "provider": "football_data",
            "league": "EPL",
            "target_date": f"{date_from}/{date_to}",
            "status": "SUCCESS",
            "items_count": count,
            "error_msg": None
        })
        print(f"[FootballDataClient] Ingested {count} EPL matches.")

    def _resolve_event_id(self, provider_id: str) -> Optional[str]:
        query = "SELECT event_id FROM event_providers WHERE provider = 'football_data' AND provider_event_id = ?"
        with get_db_connection() as conn:
            cursor = _exec(conn, query, (provider_id,))
            row = cursor.fetchone()
            if row: return row['event_id']
        return None

if __name__ == "__main__":
    # Test run
    # Requires FOOTBALL_DATA_API_KEY env var
    client = FootballDataClient()
    # Test valid range
    client.ingest_epl('2024-01-01', '2024-01-07')
