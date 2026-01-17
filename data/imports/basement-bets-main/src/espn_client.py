import requests
import time
import os
import uuid
import json
import gzip
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# Adjust imports based on project structure
try:
    from src.database import upsert_event, upsert_event_provider, upsert_game_result, log_ingestion_run, get_db_connection, _exec
except ImportError:
    # Fallback for running as script
    from database import upsert_event, upsert_event_provider, upsert_game_result, log_ingestion_run, get_db_connection, _exec

class EspnClient:
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
    RAW_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'raw', 'espn')
    
    LEAGUES = {
        'NFL': 'football/nfl',
        'NCAAM': 'basketball/mens-college-basketball',
        'EPL': 'soccer/eng.1',
        'NBA': 'basketball/nba',
        'NCAAF': 'football/college-football'
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        })
        self._last_request_time = 0
        self._rate_limit_delay = 1.0 # 1 second delay

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _save_raw_response(self, league: str, date: Optional[datetime], data: dict):
        """
        Save raw JSON to gzip file for audit.
        Format: data/raw/espn/{league}/{YYYY}/{MM}/{DD}/scoreboard.json.gz
        """
        try:
            now = datetime.now()
            target_date = date if date else now
            
            # Directory structure
            dir_path = os.path.join(
                self.RAW_DATA_DIR, 
                league, 
                target_date.strftime("%Y"), 
                target_date.strftime("%m"), 
                target_date.strftime("%d")
            )
            os.makedirs(dir_path, exist_ok=True)
            
            # Filename
            timestamp = now.strftime("%H%M%S")
            filename = f"scoreboard_{timestamp}.json.gz"
            filepath = os.path.join(dir_path, filename)
            
            with gzip.open(filepath, 'wt', encoding='utf-8') as f:
                json.dump(data, f)
                
            print(f"[EspnClient] Saved raw data to {filepath}")
        except Exception as e:
            print(f"[EspnClient] Failed to save raw data: {e}")

    def list_events(self, league: str, date_range: Tuple[datetime, datetime] = None, **kwargs) -> List[Dict]:
        path = self.LEAGUES.get(league)
        if not path:
            print(f"[EspnClient] Unsupported league: {league}")
            return []

        url = f"{self.BASE_URL}/{path}/scoreboard"
        
        params = {}
        target_date = None
        if date_range:
            params['dates'] = date_range[0].strftime("%Y%m%d")
            target_date = date_range[0]
            
        # Add extra params (e.g. groups, limit)
        params.update(kwargs)

        self._rate_limit()
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            # Save Raw
            self._save_raw_response(league, target_date, data)
            
            return self._parse_events(data, league)
        except Exception as e:
            print(f"[EspnClient] Error fetching {league} events: {e}")
            return []

    def fetch_scoreboard(self, league: str, date: datetime = None, **kwargs) -> List[Dict]:
        d_range = (date, date) if date else None
        return self.list_events(league, date_range=d_range, **kwargs)

    def _parse_events(self, data: Dict, league: str) -> List[Dict]:
        parsed = []
        events = data.get('events', [])
        
        for ev in events:
            try:
                espn_id = ev.get('id')
                date_str = ev.get('date')
                status_key = ev.get('status', {}).get('type', {}).get('name')
                
                comps = ev.get('competitions', [{}])[0]
                competitors = comps.get('competitors', [])
                
                home_team = next((c for c in competitors if c.get('homeAway') == 'home'), {})
                away_team = next((c for c in competitors if c.get('homeAway') == 'away'), {})
                
                home_name = home_team.get('team', {}).get('displayName')
                away_name = away_team.get('team', {}).get('displayName')
                
                # Scores - handle None gracefully
                h_score = home_team.get('score')
                a_score = away_team.get('score')

                status = 'scheduled'
                final = False
                if status_key == 'STATUS_FINAL':
                    status = 'final'
                    final = True
                elif status_key == 'STATUS_IN_PROGRESS':
                    status = 'in_progress'
                elif status_key == 'STATUS_POSTPONED':
                    status = 'postponed'

                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M%SZ")
                except:
                    dt = None

                event_obj = {
                    "id": str(uuid.uuid4()), # Placeholder UUID
                    "league": league,
                    "provider_id": espn_id,
                    "start_time": dt,
                    "home_team": home_name,
                    "away_team": away_name,
                    "status": status,
                    "home_score": h_score,
                    "away_score": a_score,
                    "final": final
                }
                parsed.append(event_obj)
            except Exception as e:
                print(f"[EspnClient] Error parsing event {ev.get('id')}: {e}")
                
        return parsed

    def ingest_ncaam(self, date: datetime = None):
        """
        NCAAM Specific Ingestion:
        - Must use groups=50 (Division I)
        - Must use limit=1000 to get full slate
        """
        return self.ingest_league('NCAAM', date, groups=50, limit=1000)

    def ingest_nfl(self, date: datetime = None):
        return self.ingest_league('NFL', date)

    def ingest_league(self, league: str, date: datetime = None, **kwargs):
        """
        Orchestrator to fetch and upsert events/results for a league.
        """
        print(f"[EspnClient] Ingesting {league} for {date}...")
        
        try:
            events = self.fetch_scoreboard(league, date, **kwargs)
            
            for ev in events:
                # 1. Resolve Canonical ID
                canonical_id = self._resolve_event_id(league, ev['provider_id'])
                if not canonical_id:
                    canonical_id = str(uuid.uuid4())
                    
                # 2. Upsert Event
                event_record = {
                    "id": canonical_id,
                    "league": league,
                    "start_time": ev['start_time'],
                    "home_team": ev['home_team'],
                    "away_team": ev['away_team'],
                    "status": ev['status']
                }
                upsert_event(event_record)
                
                # 3. Upsert Provider Mapping
                mapping_record = {
                    "event_id": canonical_id,
                    "provider": "espn",
                    "provider_event_id": ev['provider_id']
                }
                upsert_event_provider(mapping_record)
                
                # 4. Upsert Result (if scores exist)
                if ev['home_score'] is not None and ev['away_score'] is not None:
                    result_record = {
                        "event_id": canonical_id,
                        "home_score": int(ev['home_score']),
                        "away_score": int(ev['away_score']),
                        "final_flag": ev['final']
                    }
                    upsert_game_result(result_record)
            
            # Log Success
            log_item = {
                "provider": "espn",
                "league": league,
                "target_date": date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d"),
                "status": "SUCCESS",
                "items_count": len(events),
                "error_msg": None
            }
            log_ingestion_run(log_item)
            print(f"[EspnClient] Ingested {len(events)} events for {league}.")
            
        except Exception as e:
            # Log Failure
            print(f"[EspnClient] Ingestion Failed: {e}")
            log_item = {
                "provider": "espn",
                "league": league,
                "target_date": date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d"),
                "status": "FAILURE",
                "items_count": 0,
                "error_msg": str(e)
            }
            log_ingestion_run(log_item)

    def _resolve_event_id(self, league: str, provider_id: str) -> Optional[str]:
        query = "SELECT event_id FROM event_providers WHERE provider = 'espn' AND provider_event_id = ?"
        with get_db_connection() as conn:
            cursor = _exec(conn, query, (provider_id,))
            row = cursor.fetchone()
            if row:
                return row['event_id']
        return None

if __name__ == "__main__":
    # Ensure tables exist
    try:
        from database import init_events_db, init_ingestion_runs_db
        init_events_db()
        init_ingestion_runs_db()
    except:
        pass
        
    client = EspnClient()
    client.ingest_ncaam() # Test Full Slate Defaults
    client.ingest_nfl()
