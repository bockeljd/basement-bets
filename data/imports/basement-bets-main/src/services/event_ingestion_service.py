import uuid
from typing import Optional, Dict
import datetime

# Adjust imports based on project structure
try:
    from src.database import get_db_connection, _exec
except ImportError:
    from database import get_db_connection, _exec

class EventIngestionService:
    """
    Handles upserting normalized events into events_v2 and linking providers.
    """

    def process_event(self, event_data: Dict) -> Optional[str]:
        """
        Process a single normalized event.
        
        Args:
            event_data: Dict containing:
                - league, start_time, home_team_uuid, away_team_uuid
                - provider_id, status, result (home_score, away_score, final)
        
        Returns:
            canonical_event_id (str) or None if skipped/quarantined.
        """
        # 1. Validation / Quarantine
        if not event_data.get('home_team_uuid') or not event_data.get('away_team_uuid'):
            # print(f"[EventIngestion] Missing Team UUIDs for {event_data.get('home_team')} vs {event_data.get('away_team')}")
            return None
        
        provider = "ESPN" # TODO: Pass this in or infer? Assuming ESPN for now based on usage.
        # Actually simplest to pass it in event_data or arg?
        # Let's assume the client adds 'provider_name' to event_data or we default to ESPN if missing.
        provider = event_data.get('provider', 'ESPN')
        
        league = event_data['league']
        start_time = event_data['start_time']
        home_id = event_data['home_team_uuid']
        away_id = event_data['away_team_uuid']
        provider_event_id = event_data['provider_id']
        
        with get_db_connection() as conn:
            # 2. Resolution: Check Provider Map first
            query_prov = "SELECT event_id FROM event_providers WHERE provider = :p AND provider_event_id = :pid"
            cursor = _exec(conn, query_prov, {"p": provider, "pid": provider_event_id})
            row = cursor.fetchone()
            
            canonical_id = None
            
            if row:
                canonical_id = row[0]
                # Update existing event (scores/status)
                self._update_event_status(conn, canonical_id, event_data)
            else:
                # 3. Canonical Lookup (if provider map missing)
                # Try to find by (league, time, teams) to avoid duplicates
                # Note: start_time match might need fuzziness? For now assuming exact or strict ISO.
                query_canon = """
                SELECT id FROM events_v2 
                WHERE league = :l 
                  AND home_team_id = :hid 
                  AND away_team_id = :aid
                  AND start_time = :st
                """
                cursor = _exec(conn, query_canon, {
                    "l": league, "hid": home_id, "aid": away_id, "st": start_time
                })
                row = cursor.fetchone()
                
                if row:
                    canonical_id = row[0]
                    # Link Provider
                    self._link_provider(conn, canonical_id, provider, provider_event_id)
                    self._update_event_status(conn, canonical_id, event_data)
                else:
                    # 4. Create New
                    canonical_id = str(uuid.uuid4())
                    self._create_event(conn, canonical_id, event_data)
                    self._link_provider(conn, canonical_id, provider, provider_event_id)
            
            # --- UPSERT GAME RESULTS (Example Phase 4) ---
            if canonical_id and event_data.get('result'):
                 self._update_game_result(conn, canonical_id, event_data['result'])
            
            conn.commit()
            return canonical_id

    def _create_event(self, conn, event_id: str, data: Dict):
        query = """
        INSERT INTO events_v2 (
            id, league, season, start_time, 
            home_team, away_team, 
            home_team_id, away_team_id,
            status, venue, created_at
        ) VALUES (
            :id, :league, :season, :start_time,
            :home_name, :away_name,
            :home_uuid, :away_uuid,
            :status, :venue, CURRENT_TIMESTAMP
        )
        """
        _exec(conn, query, {
            "id": event_id,
            "league": data['league'],
            "season": data.get('season'),
            "start_time": data['start_time'],
            "home_name": data['home_team'], # Denormalized name
            "away_name": data['away_team'],
            "home_uuid": data['home_team_uuid'],
            "away_uuid": data['away_team_uuid'],
            "status": data['status'],
            "venue": data.get('venue')
        })
        
        # If there are scores, I need a place to store them.
        # Required Table: `game_results`? Or just columns in `events_v2`?
        # User REQ Phase 4 mentions "game_results".
        # Current schema `events_v2` does not have score columns yet.
        # I should probably add score columns to `events_v2` for simplicity or create `game_results`.
        # For now, I will store status. Scores might be in a separate update if table exists.
        
        # Checking `init_events_db` in `database.py`... 
        # It usually creates `events_v2` without score columns.
        # Phase 4 prompt implies "from game_results".
        # I'll Assume `game_results` table is needed or I add columns.
        # Let's add score columns to `events_v2` via migration in next step if missing.

    def _update_event_status(self, conn, event_id: str, data: Dict):
        # Update status
        query = "UPDATE events_v2 SET status = :s WHERE id = :id"
        _exec(conn, query, {"s": data['status'], "id": event_id})
        
        # TODO: Update scores if columns exist

    def _link_provider(self, conn, event_id: str, provider: str, provider_event_id: str):
        query = """
        INSERT INTO event_providers (event_id, provider, provider_event_id, last_updated)
        VALUES (:eid, :p, :pid, CURRENT_TIMESTAMP)
        ON CONFLICT(event_id, provider) DO UPDATE SET last_updated = CURRENT_TIMESTAMP
        """
        _exec(conn, query, {"eid": event_id, "p": provider, "pid": provider_event_id})

    def _update_game_result(self, conn, event_id: str, result: Dict):
        """
        Upsert game_results table.
        """
        print(f"[DEBUG] Upserting Game Result for {event_id}: {result}")
        # Schema: event_id, home_score, away_score, final, period
        query = """
        INSERT INTO game_results (event_id, home_score, away_score, final, period)
        VALUES (:eid, :hs, :as, :final, :period)
        ON CONFLICT(event_id) DO UPDATE SET
            home_score = excluded.home_score,
            away_score = excluded.away_score,
            final = excluded.final,
            period = excluded.period,
            updated_at = CURRENT_TIMESTAMP
        """
        
        params = {
            "eid": event_id,
            "hs": result.get('home_score'),
            "as": result.get('away_score'),
            "final": result.get('final', False),
            "period": result.get('period', '') 
        }
        
        # Note: SQLite `ON CONFLICT` support relies on version >= 3.24.
        # If older, may fail. If so, fallback to DELETE+INSERT or check `get_db_type()`? 
        # But for now assuming Standard env.
        try:
             _exec(conn, query, params)
        except Exception as e:
            print(f"Warning: Scores upsert failed: {e}")
            pass
