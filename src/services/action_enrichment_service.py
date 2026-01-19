import hashlib
import json
import datetime
import uuid
from typing import Dict, List, Optional
from src.database import get_db_connection, _exec
from src.services.odds_fetcher_service import OddsFetcherService
from src.services.event_linker import EventLinker

class ActionEnrichmentService:
    def __init__(self):
        self.fetcher = OddsFetcherService()
        self.linker = EventLinker()
        
    def _generate_fingerprint(self, *args) -> str:
        s = "|".join(str(a) for a in args)
        return hashlib.sha256(s.encode()).hexdigest()

    def ingest_enrichment_for_league(self, league: str, date_str: str = None) -> Dict:
        """
        Main entry point.
        """
        if not date_str:
            date_str = datetime.datetime.now().strftime("%Y%m%d")
            
        print(f"[Enrichment] Fetching {league} for {date_str}...")
        
        # 1. Fetch from Action Network (reuse existing fetcher logic)
        # Note: fetch_odds parses data. We might need raw data for enrichment payload.
        # But fetch_odds returns a cleaned list. 
        # The prompt requires storing the "payload_json". 
        # So I should probably modify OddsFetcher to return raw or re-request here.
        # To avoid breaking existing code, I'll re-request similar to fetch_odds but keep raw.
        
        # Actually, OddsFetcher parses internal structure. 
        # I'll implement a raw fetch here to get the full json for `action_game_enrichment`.
        
        raw_games = self._fetch_raw(league, date_str)
        print(f"[Enrichment] Found {len(raw_games)} games.")
        
        stats = {
            "games_processed": 0,
            "enrichment_saved": 0,
            "splits_saved": 0,
            "errors": 0
        }
        
        for game in raw_games:
            try:
                self._process_game(game, league)
                stats["games_processed"] += 1
            except Exception as e:
                print(f"[Enrichment] Failed to process game {game.get('id')}: {e}")
                stats["errors"] += 1
                
        return stats

    def _fetch_raw(self, league: str, date_str: str) -> List[Dict]:
        """
        Direct fetch to get full JSON payload.
        """
        # Mapping from OddsFetcherService
        sport_map = {
            'NBA': 'nba', 'NFL': 'nfl', 'MLB': 'mlb', 
            'NCAAM': 'ncaab', 'NCAAF': 'ncaaf', 'EPL': 'soccer'
        }
        api_sport = sport_map.get(league, league.lower())
        
        url = f"https://api.actionnetwork.com/web/v1/scoreboard/{api_sport}?date={date_str}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
        }
        
        import requests
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get('games', [])

    def _process_game(self, game: Dict, league: str):
        # 1. Resolve Canonical Event ID
        # We need (Home, Away, Date)
        home_team_id = game.get('home_team_id')
        away_team_id = game.get('away_team_id')
        
        # Extract names from teams array
        home_name = "Unknown"
        away_name = "Unknown"
        for t in game.get('teams', []):
            if t['id'] == home_team_id: home_name = t['full_name']
            if t['id'] == away_team_id: away_name = t['full_name']
            
        start_time_iso = game.get('start_time')
        # Parse ISO to YYYY-MM-DD
        try:
            dt = datetime.datetime.fromisoformat(start_time_iso.replace('Z', '+00:00'))
            date_str = dt.strftime("%Y-%m-%d")
        except:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")

        # Link!
        # Use link_leg with sufficient context to find the event.
        # We pass one team as the selection to anchor key matching.
        mock_leg = {
            "selection": home_name,
            "team": home_name
        }
        description = f"{home_name} vs {away_name}"
        
        link_res = self.linker.link_leg(mock_leg, league, date_str, description=description)
        
        event_id = link_res.get('event_id')
        if not event_id or link_res.get('link_status') != 'LINKED':
            # Try linking with away team if home failed?
            mock_leg_away = {"selection": away_name, "team": away_name}
            link_res = self.linker.link_leg(mock_leg_away, league, date_str, description=description)
            event_id = link_res.get('event_id')
            
            if not event_id:
                # print(f"Skipping enrichment for {home_name} vs {away_name} (No Link: {link_res.get('reason')})")
                return 

        # 2. Store Raw Enrichment
        self._store_raw_enrichment(event_id, game)
        
        # 3. Extract Splits
        self._extract_splits(event_id, game)
        
        # 4. Extract Props/Injuries (Placeholder)
        pass

    def _store_raw_enrichment(self, event_id: str, game_data: Dict):
        payload_str = json.dumps(game_data)
        provider_game_id = str(game_data.get('id'))
        
        # Fingerprint: event_id + time_bucket (e.g. hourly) + payload_hash
        # Actually payload hash alone is good for dedupe if identical
        payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
        
        # But we want to capture history. So timestamp matters.
        # Let's bucket timestamp to 1 hour to avoid noise? 
        # Or just insert unique payloads.
        # Using payload_hash ensuring we only store NEW data.
        fingerprint = self._generate_fingerprint(event_id, payload_hash)
        
        with get_db_connection() as conn:
            # UUID handler for Postgres vs Sqlite? 
            # In SQLite we use string. In PG we use string for input and let driver cast or ensure we pass UUID obj.
            # For simplicity, passing string usually works if driver handles it, or explicit.
            
            # Simple Insert w/ IGNORE on fingerprint
            ins = """
            INSERT INTO action_game_enrichment 
            (id, event_id, provider_game_id, payload_json, fingerprint)
            VALUES (?, ?, ?, ?, ?)
            """
            # Adjust params for PG in _exec helper
            
            # ID generation
            row_id = str(uuid.uuid4())
            
            try:
                _exec(conn, ins, (row_id, str(event_id), provider_game_id, payload_str, fingerprint))
                conn.commit()
            except Exception as e:
                # Likely Unique Constraint -> Data hasn't changed
                pass

    def _extract_splits(self, event_id: str, game_data: Dict):
        odds_list = game_data.get('odds', [])
        if not odds_list: return
        
        # Typically the first odds object has the consensus/public stats
        # We iterate to find one with stats
        target_odd = None
        for o in odds_list:
            if o.get('ml_home_public') is not None or o.get('spread_home_money') is not None:
                target_odd = o
                break
        
        # If none found, we can't extract specific splits, but maybe we extract the first one anyway if we want to log nulls?
        # User constraint: "Tables populate only when data exists". So we skip if null.
        if not target_odd: return
        
        # Mapping fields
        # market_type, selection, line, bet_pct, handle_pct
        
        splits = []
        
        # Moneyline
        if target_odd.get('ml_home_public'):
            splits.append({
                "market": "ML", "selection": "HOME", 
                "bet_pct": target_odd.get('ml_home_public'), "handle_pct": target_odd.get('ml_home_money')
            })
        if target_odd.get('ml_away_public'):
            splits.append({
                "market": "ML", "selection": "AWAY", 
                "bet_pct": target_odd.get('ml_away_public'), "handle_pct": target_odd.get('ml_away_money')
            })
            
        # Spread
        if target_odd.get('spread_home_public'):
            splits.append({
                "market": "SPREAD", "selection": "HOME", "line": target_odd.get('spread_home'),
                "bet_pct": target_odd.get('spread_home_public'), "handle_pct": target_odd.get('spread_home_money')
            })
        if target_odd.get('spread_away_public'):
            splits.append({
                "market": "SPREAD", "selection": "AWAY", "line": target_odd.get('spread_away'),
                "bet_pct": target_odd.get('spread_away_public'), "handle_pct": target_odd.get('spread_away_money')
            })
            
        # Total
        if target_odd.get('total_over_public'):
            splits.append({
                "market": "TOTAL", "selection": "OVER", "line": target_odd.get('total'),
                "bet_pct": target_odd.get('total_over_public'), "handle_pct": target_odd.get('total_over_money')
            })
        if target_odd.get('total_under_public'):
            splits.append({
                "market": "TOTAL", "selection": "UNDER", "line": target_odd.get('total'),
                "bet_pct": target_odd.get('total_under_public'), "handle_pct": target_odd.get('total_under_money')
            })
            
        # Insert
        for s in splits:
             row_id = str(uuid.uuid4())
             # Fingerprint: event_id + market + selection + bet_pct + handle_pct + timestamp_bucket?
             # If values change, we want new row? Or update?
             # "action_splits" implies history. So unique on time.
             # Bucket time to hour?
             ts_bucket = datetime.datetime.now().strftime("%Y%m%d%H")
             
             fp = self._generate_fingerprint(event_id, s['market'], s['selection'], s.get('bet_pct'), s.get('handle_pct'), ts_bucket)
             
             ins = """
             INSERT INTO action_splits
             (id, event_id, market_type, selection, line, bet_pct, handle_pct, as_of_ts, fingerprint)
             VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
             """
             with get_db_connection() as conn:
                 try:
                     _exec(conn, ins, (
                         row_id, str(event_id), s['market'], s['selection'], s.get('line'),
                         s.get('bet_pct'), s.get('handle_pct'), fp
                     ))
                     conn.commit()
                 except:
                     pass
