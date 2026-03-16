
import re
from typing import Optional, List
from src.database import get_db_connection, _exec

class TeamMatcher:
    """
    Utility to resolve Event Team Names (e.g. 'Duke Blue Devils')
    to Data Source Names (e.g. 'Duke' in Torvik/KenPom).
    """

    # Class-level cache to share across instances
    _source_names_cache = {}

    def __init__(self):
        self._cache = {}

    def normalize(self, name: str) -> str:
        """Basic normalization (lower, strip)"""
        if not name: return ""
        return re.sub(r'[^a-zA-Z0-9\s]', '', name.lower()).strip()

    def find_source_name(self, event_team_name: str, source_table: str, source_col: str) -> Optional[str]:
        """
        Find the matching name in the source table.
        Heuristics:
        1. Exact Match (norm)
        2. Prefix Match (e.g. 'Duke' in 'Duke Blue Devils')
        3. Common Aliases
        """
        cache_key = (event_team_name, source_table)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Use class-level cache for source names to avoid repeated SELECT DISTINCT
        source_cache_key = (source_table, source_col)
        if source_cache_key not in TeamMatcher._source_names_cache:
            with get_db_connection() as conn:
                # Use a more efficient query or just fetch known teams
                # If these are metrics tables, fetching DISTINCT team names once is best.
                rows = _exec(conn, f"SELECT DISTINCT {source_col} FROM {source_table}").fetchall()
                TeamMatcher._source_names_cache[source_cache_key] = [r[0] for r in rows if r[0]]
        
        source_names = TeamMatcher._source_names_cache[source_cache_key]
        norm_event = self.normalize(event_team_name)
        
        best_match = None
        
        # 1. Exact Match Check
        for s in source_names:
            if self.normalize(s) == norm_event:
                best_match = s
                break
        
        # 2. Substring/Prefix Check
        if not best_match:
            candidates = []
            for s in source_names:
                norm_s = self.normalize(s)
                if norm_event.startswith(norm_s):
                     if len(norm_s) < len(norm_event) and norm_event[len(norm_s)] != ' ':
                         continue
                     candidates.append(s)
            
            if candidates:
                candidates.sort(key=lambda x: len(x), reverse=True)
                best_match = candidates[0]
        
        # 3. Hardcoded Fixes
        if not best_match:
            manual_map = {
                "southern miss golden eagles": "Southern Miss",
                "miami fl hurricanes": "Miami FL",
                "miami (fl) hurricanes": "Miami FL",
                "uconn huskies": "Connecticut",
                "ole miss rebels": "Ole Miss",
            }
            for k, v in manual_map.items():
                if k in norm_event:
                    for s in source_names:
                        if self.normalize(s) == self.normalize(v):
                            best_match = s
                            break
                    if best_match: break
        
        self._cache[cache_key] = best_match
        return best_match
