import requests
import uuid
import datetime
from typing import List, Dict, Optional
from src.database import upsert_event, upsert_event_provider, get_db_connection, _exec

class EspnScoreboardClient:
    """
    Client for ESPN Scoreboard API (site.api.espn.com).
    Enforces ESPN IDs as canonical event keys.
    """
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
    
    LEAGUE_MAP = {
        'NFL': 'football/nfl',
        'NCAAM': 'basketball/mens-college-basketball',
        'NBA': 'basketball/nba',
        'EPL': 'soccer/eng.1',
        'NCAAF': 'football/college-football'
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        })

    def fetch_events(self, league: str, date: str = None) -> List[Dict]:
        """
        Fetch events for a specific league and date.
        date format: YYYYMMDD
        """
        path = self.LEAGUE_MAP.get(league.upper())
        if not path:
            print(f"[ESPN v2] Unsupported league: {league}")
            return []
            
        url = f"{self.BASE_URL}/{path}/scoreboard"
        params = {'limit': 1000, 'groups': 50}
        if date:
            params['dates'] = date
            
        print(f"[ESPN v2] Fetching {league} scoreboard for {date or 'TODAY'}...")
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            events = data.get('events', [])
            normalized = []
            
            for ev in events:
                try:
                    espn_id = ev['id']
                    comp = ev['competitions'][0]
                    competitors = comp['competitors']
                    
                    home = next(c for c in competitors if c['homeAway'] == 'home')
                    away = next(c for c in competitors if c['homeAway'] == 'away')
                    
                    status_raw = ev['status']['type']['name']
                    
                    norm_ev = {
                        "id": f"espn:{league.lower()}:{espn_id}", # STRICT CANONICAL ID
                        "league": league.upper(),
                        "start_time": ev['date'], # ISO string
                        "home_team": home['team']['displayName'],
                        "home_team_id": home['team']['id'],
                        "away_team": away['team']['displayName'],
                        "away_team_id": away['team']['id'],
                        "status": status_raw
                    }
                    normalized.append(norm_ev)
                    
                    # 4. Result Enrichment
                    score_res = None
                    if status_raw in ['STATUS_FINAL', 'STATUS_FULL_TIME']:
                        score_res = {
                            "event_id": norm_ev["id"],
                            "home_score": int(home.get('score', 0)),
                            "away_score": int(away.get('score', 0)),
                            "final": True,
                            "period": ev['status']['type'].get('detail', 'Final')
                        }
                    
                    # PERSIST TO DB
                    self._upsert_to_db(norm_ev, espn_id, score_res)
                    
                except Exception as e:
                    print(f"[ESPN v2] Error parsing event {ev.get('id')}: {e}")
                    
            print(f"[ESPN v2] Processed {len(normalized)} events.")
            return normalized
            
        except Exception as e:
            print(f"[ESPN v2] Error fetching scoreboard: {e}")
            return []

    def _upsert_to_db(self, event: dict, espn_id: str, result: Optional[dict] = None):
        """
        Upsert canonical event, provider mapping, and results.
        """
        from src.database import upsert_game_result
        
        # 1. Upsert Event (Primary Table)
        upsert_event(event)
        
        # 2. Upsert Provider Mapping
        mapping = {
            "event_id": event['id'],
            "provider": "espn",
            "provider_event_id": str(espn_id)
        }
        upsert_event_provider(mapping)

        # 3. Upsert Results (if final)
        if result:
            upsert_game_result(result)

if __name__ == "__main__":
    # Quick Test
    client = EspnScoreboardClient()
    events = client.fetch_events('NCAAM')
    if events:
        print(f"Sample: {events[0]['home_team']} vs {events[0]['away_team']} (ID: {events[0]['id']})")
