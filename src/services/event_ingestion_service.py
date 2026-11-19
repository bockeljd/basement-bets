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
    Handles upserting normalized events into canonical 'events' table and linking providers.
    """

    def process_event(self, event_data: Dict) -> Optional[str]:
        """
        Process a single normalized event.
        """
        if not event_data.get('home_team_uuid') or not event_data.get('away_team_uuid'):
            return None
        
        provider = event_data.get('provider', 'ESPN')
        league = event_data['league']
        start_time = event_data['start_time']
        home_id = event_data['home_team_uuid']
        away_id = event_data['away_team_uuid']
        provider_event_id = event_data['provider_id']
        
        with get_db_connection() as conn:
            # 1. Resolution: Check Provider Map first
            query_prov = "SELECT event_id FROM event_providers WHERE provider = :p AND provider_event_id = :pid"
            cursor = _exec(conn, query_prov, {"p": provider, "pid": provider_event_id})
            row = cursor.fetchone()
            
            canonical_id = None
            
            if row:
                canonical_id = row[0]
                self._update_event_status(conn, canonical_id, event_data)
            else:
                # 2. Canonical Lookup (if provider map missing)
                query_canon = """
                SELECT id FROM events 
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
                    self._link_provider(conn, canonical_id, provider, provider_event_id)
                    self._update_event_status(conn, canonical_id, event_data)
                else:
                    # 2b. Fuzzy matchup lookup within +/-24h (prevents duplicate espn:ncaam:* rows alongside action:ncaam:*)
                    matched_existing = None
                    try:
                        from src.services.injury_service import _team_names_match
                        from src.utils.team_matcher import TeamMatcher
                        matcher = TeamMatcher()
                        cand_rows = _exec(
                            conn,
                            """
                            SELECT id, home_team, away_team
                            FROM events
                            WHERE league = :l
                              AND start_time BETWEEN (:st::timestamptz - INTERVAL '24 hours') AND (:st::timestamptz + INTERVAL '24 hours')
                            ORDER BY (CASE WHEN id LIKE 'action:%%' THEN 0 ELSE 1 END), start_time ASC
                            """,
                            {"l": league, "st": start_time},
                        ).fetchall()
                        h_in = event_data.get('home_team')
                        a_in = event_data.get('away_team')
                        for cr in (cand_rows or []):
                            crd = dict(cr)
                            direct = _team_names_match(matcher, crd.get('home_team'), h_in) and _team_names_match(matcher, crd.get('away_team'), a_in)
                            swapped = (not direct) and _team_names_match(matcher, crd.get('home_team'), a_in) and _team_names_match(matcher, crd.get('away_team'), h_in)
                            if direct or swapped:
                                matched_existing = (crd['id'], swapped)
                                break
                    except Exception:
                        matched_existing = None

                    if matched_existing:
                        canonical_id, was_swapped = matched_existing
                        self._link_provider(conn, canonical_id, provider, provider_event_id)
                        self._update_event_status(conn, canonical_id, event_data)
                        if was_swapped and isinstance(event_data.get('result'), dict):
                            r_orig = event_data['result']
                            event_data = {
                                **event_data,
                                'result': {
                                    **r_orig,
                                    'home_score': r_orig.get('away_score'),
                                    'away_score': r_orig.get('home_score'),
                                },
                            }
                    else:
                        # 3. Create New
                        if league.upper() == 'NCAAM':
                            canonical_id = f"espn:ncaam:{provider_event_id}"
                        else:
                            canonical_id = str(uuid.uuid4())
                            
                        self._create_event(conn, canonical_id, event_data)
                        self._link_provider(conn, canonical_id, provider, provider_event_id)
            
            # 4. Upsert Game Results
            if canonical_id and event_data.get('result'):
                 self._update_game_result(conn, canonical_id, event_data['result'])
            
            conn.commit()
            return canonical_id

    def _create_event(self, conn, event_id: str, data: Dict):
        query = """
        INSERT INTO events (
            id, league, start_time, 
            home_team, away_team, 
            home_team_id, away_team_id,
            status, neutral_site, venue, venue_city, venue_state, created_at
        ) VALUES (
            :id, :league, :start_time,
            :home_name, :away_name,
            :home_uuid, :away_uuid,
            :status, :neutral_site, :venue, :venue_city, :venue_state, CURRENT_TIMESTAMP
        )
        """
        _exec(conn, query, {
            "id": event_id,
            "league": data['league'],
            "start_time": data['start_time'],
            "home_name": data['home_team'],
            "away_name": data['away_team'],
            "home_uuid": data['home_team_uuid'],
            "away_uuid": data['away_team_uuid'],
            "status": data['status'],
            "neutral_site": bool(data.get('neutral_site', False)),
            "venue": data.get('venue'),
            "venue_city": data.get('venue_city'),
            "venue_state": data.get('venue_state'),
        })

    def _update_event_status(self, conn, event_id: str, data: Dict):
        query = """
        UPDATE events
        SET status = :s,
            start_time = :st,
            neutral_site = COALESCE(:ns, neutral_site),
            venue = COALESCE(:v, venue),
            venue_city = COALESCE(:vc, venue_city),
            venue_state = COALESCE(:vs, venue_state)
        WHERE id = :id
        """
        try:
            _exec(conn, query, {
                "s": data['status'],
                "st": data['start_time'],
                "ns": data.get('neutral_site'),
                "v": data.get('venue'),
                "vc": data.get('venue_city'),
                "vs": data.get('venue_state'),
                "id": event_id,
            })
        except Exception as e:
            # Fallback if legacy schema lacks venue/neutral columns
            print(f"Failed to update status and start_time for {event_id}: {e}")
            query = "UPDATE events SET status = :s WHERE id = :id"
            _exec(conn, query, {"s": data['status'], "id": event_id})

    def _link_provider(self, conn, event_id: str, provider: str, provider_event_id: str):
        query = """
        INSERT INTO event_providers (event_id, provider, provider_event_id, last_updated)
        VALUES (:eid, :p, :pid, CURRENT_TIMESTAMP)
        ON CONFLICT(event_id, provider) DO UPDATE SET last_updated = CURRENT_TIMESTAMP
        """
        _exec(conn, query, {"eid": event_id, "p": provider, "pid": provider_event_id})

    def _update_game_result(self, conn, event_id: str, result: Dict):
        query = """
        INSERT INTO game_results (event_id, home_score, away_score, final)
        VALUES (:eid, :hs, :as, :final)
        ON CONFLICT(event_id) DO UPDATE SET
            home_score = excluded.home_score,
            away_score = excluded.away_score,
            final = excluded.final,
            updated_at = CURRENT_TIMESTAMP
        """
        params = {
            "eid": event_id,
            "hs": result.get('home_score'),
            "as": result.get('away_score'),
            "final": result.get('final', False)
        }
        try:
             _exec(conn, query, params)
        except Exception as e:
            print(f"Warning: Scores upsert failed: {e}")
            pass
