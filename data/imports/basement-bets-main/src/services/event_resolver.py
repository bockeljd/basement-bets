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
    Links bet legs to canonical events_v2 using fuzzy matching and constraints.
    """
    
    def __init__(self):
        self.identity = TeamIdentityService()
    
    def resolve_event_id_for_leg(self, leg: Dict, sport: str, bet_date: str, bet_description: str = None) -> Optional[str]:
        """
        Attempt to resolve a canonical event ID for a given leg.
        
        Args:
           leg: dict with 'selection', 'leg_type', 'market_key'
           sport: e.g. 'NFL', 'NCAAM'
           bet_date: 'YYYY-MM-DD'
           bet_description: (Optional) context from parent bet
           
        Returns:
           event_id (uuid string) or None
        """
        selection = leg.get('selection', '')
        # 1. Extract Potential Team Name
        candidates = self._extract_names(selection)
        
        if not candidates and bet_description:
            # Fallback: Extract from Description
            # e.g. "Parlay (3 legs): UNC Wilmington vs Hampton ..."
            # We can extract all potential teams from description?
            # Or just rely on heuristics.
            candidates = self._extract_names(bet_description)
            
        if not candidates:
             return None

        # 2. Resolve Team Identity
        team_id = None
        for name in candidates:
            # Try exact/alias match
            # We map 'NCAAM' sport to 'NCAAM' league, 'NFL' to 'NFL'
            tid = self.identity.get_team_by_name(name, sport) # Need to add this method to IdentityService or just use SQL
            if tid:
                team_id = tid
                break
        
        if not team_id:
            # Try simple SQL lookup on alias table directly if service doesn't have the method
             with get_db_connection() as conn:
                for name in candidates:
                    norm = name.lower().strip()
                    row = _exec(conn, "SELECT team_id FROM team_aliases WHERE alias = :a", {"a": norm}).fetchone()
                    if row:
                        team_id = row[0]
                        break
        
        if not team_id:
            return None # Failed to identify team

        # 3. Search Events
        # Window: Bet Date +/- 1 day (handled in SQL)
        # We search where home_team_id OR away_team_id matches
        found_event_id = None
        
        with get_db_connection() as conn:
            query = """
            SELECT id, start_time, home_team_id, away_team_id, league 
            FROM events_v2
            WHERE league = :l
              AND (home_team_id = :tid OR away_team_id = :tid)
              AND start_time >= :start AND start_time <= :end
            """
            # Date window
            try:
                dt = datetime.datetime.strptime(bet_date, "%Y-%m-%d")
            except:
                # Try iso
                dt = datetime.datetime.fromisoformat(bet_date)
            
            start_window = dt - datetime.timedelta(days=1)
            end_window = dt + datetime.timedelta(days=2) # +2 to be safe for late games
            
            rows = _exec(conn, query, {
                "l": sport, 
                "tid": team_id,
                "start": start_window.isoformat(),
                "end": end_window.isoformat()
            }).fetchall()
            
            # 4. Ambiguity Check
            if len(rows) == 1:
                found_event_id = rows[0][0]
            elif len(rows) > 1:
                # Multiple games? (Doubleheader or dense schedule)
                # Pick separate by closest time if we had exact leg time, but we usually just have bet date.
                # Logic: Return None and log ambiguity
                pass
                
        return found_event_id

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
