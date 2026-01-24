import re
import datetime
from typing import Optional, Dict, List
import json

try:
    from src.database import get_db_connection, _exec
    from src.services.team_identity_service import TeamIdentityService
except ImportError:
    from database import get_db_connection, _exec
    from services.team_identity_service import TeamIdentityService

class EventResolver:
    """
    Links bet legs to canonical events using fuzzy matching and constraints.
    """
    
    def __init__(self):
        self.identity = TeamIdentityService()
    
    def resolve_event_id_for_leg(self, leg: Dict, sport: str, bet_date: str, bet_description: str = None) -> Optional[str]:
        """
        Backward compatible method. Returns ID if exactly one high-confidence match found.
        """
        candidates = self.find_candidates(leg, sport, bet_date, bet_description)
        if len(candidates) == 1:
             return candidates[0]['event_id']
        return None

    def find_candidates(self, leg: Dict, sport: str, bet_date: str, bet_description: str = None) -> List[Dict]:
        """
        Find potential event matches with scores.
        Returns: 
           [ {'event_id': str, 'score': float, 'reason': str, 'selection_team_id': str} ]
        """
        selection = leg.get('selection', '')
        extracted_names = self._extract_names(selection)
        
        if not extracted_names and bet_description:
            extracted_names = self._extract_names(bet_description)
            
        if not extracted_names:
            return []

        # 2. Resolve Team Identity
        team_ids = []
        for name in extracted_names:
            tid = self.identity.get_team_by_name(name, sport)
            if tid:
                team_ids.append(tid)
            else:
                 with get_db_connection() as conn:
                    norm = name.lower().strip()
                    row = _exec(conn, "SELECT team_id FROM team_aliases WHERE alias = :a", {"a": norm}).fetchone()
                    if row:
                        team_ids.append(row[0])

        if not team_ids:
            return []
            
        # 3. Search Events
        # Window: Bet Date +/- 1 day
        start_date = None
        try:
            dt = datetime.datetime.strptime(bet_date, "%Y-%m-%d")
            start_date = dt
        except:
             try:
                 dt = datetime.datetime.fromisoformat(bet_date)
                 start_date = dt
             except:
                 pass
                 
        if not start_date:
            return [] # Can't search without date

        start_window = start_date - datetime.timedelta(days=1)
        end_window = start_date + datetime.timedelta(days=2)
        
        unique_matches = {} # event_id -> candidate
        
        with get_db_connection() as conn:
            query = """
            SELECT id, start_time, home_team_id, away_team_id, league 
            FROM events
            WHERE league = :l
              AND (home_team_id = ANY(:tids) OR away_team_id = ANY(:tids))
              AND start_time >= :start AND start_time <= :end
            """
            # SQLite doesn't support ANY array syntax easily, need loop or IN clause.
            # Helper to handle both (or just loop for now since team_ids is small)
            
            # Simple loop for compatibility
            for tid in team_ids:
                 q = """
                 SELECT id, start_time, home_team_id, away_team_id, league 
                 FROM events
                 WHERE league = :l
                   AND (home_team_id = :tid OR away_team_id = :tid)
                   AND start_time >= :start AND start_time <= :end
                 """
                 rows = _exec(conn, q, {
                    "l": sport, 
                    "tid": tid,
                    "start": start_window.isoformat(),
                    "end": end_window.isoformat()
                 }).fetchall()
                 
                 for r in rows:
                     eid = r[0]
                     unique_matches[eid] = {
                         "event_id": eid,
                         "score": 1.0, # Perfect match on team ID
                         "reason": f"Matched team_id {tid}",
                         "selection_team_id": tid
                     }

        return list(unique_matches.values())

    def _extract_names(self, text: str) -> List[str]:
        # Very basic extractor
        # Remove digits, +/-, and "Over", "Under"
        # "Kansas City Chiefs -3.5" -> "Kansas City Chiefs"
        # "A vs B" -> ["A", "B"]
        s = text
        s = re.sub(r'\b(vs\.?|versus|@)\b', '|', s, flags=re.IGNORECASE)
        s = re.sub(r'[\+\-]?\d+(\.\d+)?', '', s)
        s = s.replace('Over', '').replace('Under', '')
        
        candidates = []
        for part in s.split('|'):
            clean = part.strip()
            if clean:
                candidates.append(clean)
        return candidates
