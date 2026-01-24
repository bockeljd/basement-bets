import requests
import json
import datetime
from typing import List, Dict, Optional
import os
import sys

# Ensure src is in path for IngestionEngine import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from src.ingestion_engine import IngestionEngine
    # Import Identity Service
    from src.services.team_identity_service import TeamIdentityService
    from src.services.event_ingestion_service import EventIngestionService
except ImportError:
    from ingestion_engine import IngestionEngine
    from services.team_identity_service import TeamIdentityService
    from services.event_ingestion_service import EventIngestionService

class EspnClient(IngestionEngine):
    """
    Client for ESPN Hidden API (Scoreboard).
    Supports: NFL, NCAAM.
    """
    
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
    
    LEAGUE_MAP = {
        'NFL': 'football/nfl',
        'NCAAM': 'basketball/mens-college-basketball',
        'NBA': 'basketball/nba',
        'EPL': 'soccer/eng.1'
    }

    def __init__(self):
        super().__init__()
        self.identity = TeamIdentityService()
        self.events_service = EventIngestionService()

    def fetch_scoreboard(self, league: str, date: str = None, **kwargs) -> List[Dict]:
        """
        Fetch scoreboard for a specific league and date.
        Date fmt: YYYYMMDD
        """
        path = self.LEAGUE_MAP.get(league)
        if not path:
            print(f"[ESPN] Unsupported league: {league}")
            return []
            
        url = f"{self.BASE_URL}/{path}/scoreboard"
        params = {'limit': 1000} # Get all games
        if date:
            params['dates'] = date
            
        # Merge kwargs into params (e.g. groups=50)
        params.update(kwargs)
            
        print(f"[ESPN] Fetching {league} scoreboard for {date or 'TODAY'}...")
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            # Use IngestionEngine to persist/check drift
            # We expect 'events' key
            # Expected items keys for drift: id, date, name, status, competitions
            events = data.get('events', [])
            
            # Ingest raw payload
            # Note: We pass the WHOLE payload or list of events?
            # User requirement: "Store raw payload snapshots".
            # The 'data' object is the raw payload.
            self.ingest_data("ESPN", league, data, expected_keys={'events', 'leagues', 'season'})
            
            normalized = self._normalize_events(events, league)
            
            # --- INGEST EVENTS INTO DB ---
            count_ingested = 0
            for nev in normalized:
                try:
                    # Enrich with provider if needed (defaults to ESPN in service if missing, but better explicit)
                    nev['provider'] = 'ESPN'
                    canonical_id = self.events_service.process_event(nev)
                    if canonical_id:
                        nev['id'] = canonical_id # Stabilize ID for frontend
                        count_ingested += 1
                except Exception as e:
                    print(f"[ESPN] Error ingesting event for DB: {e}")
            
            if count_ingested > 0:
                print(f"[ESPN] Ingested {count_ingested} canonical events.")
            
            return normalized
            
        except Exception as e:
            print(f"[ESPN] Error fetching scoreboard: {e}")
            return []

    def _normalize_events(self, events: List[Dict], league: str) -> List[Dict]:
        """
        Convert raw ESPN events to canonical dicts.
        lazily seeds teams.
        """
        normalized = []
        for ev in events:
            try:
                # Basic parsing
                comp = ev['competitions'][0]
                competitors = comp['competitors']
                
                home = next(c for c in competitors if c['homeAway'] == 'home')
                away = next(c for c in competitors if c['homeAway'] == 'away')
                
                # Status: STATUS_SCHEDULED, STATUS_FINAL, STATUS_IN_PROGRESS
                status_raw = ev['status']['type']['name']
                
                # Results (if applicable)
                home_score = int(home.get('score', 0)) if home.get('score') else 0
                away_score = int(away.get('score', 0)) if away.get('score') else 0
                
                # LAZY SEEDING
                home_id = self.identity.get_or_create_team(
                    league=league,
                    provider="ESPN",
                    provider_team_id=home['team']['id'],
                    provider_team_name=home['team']['displayName'],
                    abbreviation=home['team'].get('abbreviation')
                )
                
                away_id = self.identity.get_or_create_team(
                    league=league,
                    provider="ESPN",
                    provider_team_id=away['team']['id'],
                    provider_team_name=away['team']['displayName'],
                    abbreviation=away['team'].get('abbreviation')
                )
                
                norm_event = {
                    "id": None, # Canonical ID not generated yet.
                    "provider_id": ev['id'],
                    "league": league,
                    "season": ev.get('season', {}).get('year'),
                    "start_time": ev['date'], # ISO string
                    "home_team": home['team']['displayName'],
                    "home_team_id": home['team']['id'],
                    "home_team_uuid": home_id,
                    "away_team": away['team']['displayName'],
                    "away_team_id": away['team']['id'],
                    "away_team_uuid": away_id,
                    "status": status_raw,
                    "venue": comp.get('venue', {}).get('fullName'),
                    "result": {
                        "home_score": home_score,
                        "away_score": away_score,
                        "final": status_raw == 'STATUS_FINAL'
                    }
                }
                normalized.append(norm_event)
            except Exception as e:
                # print(f"[ESPN] Failed to parse event {ev.get('id', '?')}: {e}")
                pass
                
        return normalized

if __name__ == "__main__":
    # Smoke Test
    client = EspnClient()
    events = client.fetch_scoreboard('NCAAM') # Default to today
    print(f"Parsed {len(events)} events.")
    if events:
        print("Sample:", events[0])
