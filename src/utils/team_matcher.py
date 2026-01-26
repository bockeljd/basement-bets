
import re
from typing import Optional, List
from src.database import get_db_connection, _exec

class TeamMatcher:
    """
    Utility to resolve Event Team Names (e.g. 'Duke Blue Devils')
    to Data Source Names (e.g. 'Duke' in Torvik/KenPom).
    """

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

        norm_event = self.normalize(event_team_name)
        
        with get_db_connection() as conn:
            # Fetch all candidate names from source
            # This is cached in memory per instance usually, but for now we fetch simply
            # Optimization: fetch distinct names once? No, do it query time for simplicity or fetch all
            
            # Let's fetch all source names once per call or use a LIKE query?
            # Fetching all ~360 names is cheap.
            rows = _exec(conn, f"SELECT DISTINCT {source_col} FROM {source_table}").fetchall()
            source_names = [r[0] for r in rows if r[0]]

        best_match = None
        
        # 1. Exact Match Check
        for s in source_names:
            if self.normalize(s) == norm_event:
                best_match = s
                break
        
        # 2. Substring/Prefix Check
        # Find ALL candidates that are prefixes, then pick longest
        candidates = []
        for s in source_names:
            norm_s = self.normalize(s)
            if norm_event.startswith(norm_s):
                 # Length/Diff check
                 if len(norm_event) > len(norm_s):
                     # Boundary check: next char must be space if not end (implied by len check and regex norm)
                     # Normalized string "southern miss golden eagles" starts with "southern" (len 8). Next char at 8 is ' '.
                     # Starts with "southern miss" (len 13). Next char at 13 is ' '.
                     # Logic:
                     if len(norm_s) < len(norm_event) and norm_event[len(norm_s)] != ' ':
                         continue # E.g. "Io" in "Iowa" -> "io" (2) != "iowa" (4). norm_event[2] is 'w'. Skip.
                     
                     candidates.append(s)
        
        if candidates:
            # Sort by length descending (Longest match is best match)
            # e.g. ["Southern", "Southern Miss"] -> "Southern Miss"
            candidates.sort(key=lambda x: len(x), reverse=True)
            best_match = candidates[0]
        
        # 3. Reverse Check (Source 'Miami FL' vs 'Miami') - hard to generalize
        
        # 4. Hardcoded Fixes (if needed)
        # e.g. "Southern Miss" vs "Southern Mississippi"
        if not best_match:
            # Quick Map
            manual_map = {
                "southern miss golden eagles": "Southern Miss",
                "miami fl hurricanes": "Miami FL",
                "miami (fl) hurricanes": "Miami FL",
                "uconn huskies": "Connecticut", # Torvik uses different names sometimes
                "ole miss rebels": "Ole Miss",
            }
            # Check map
            for k, v in manual_map.items():
                if k in norm_event:
                    # Check if v is in source_names
                    # This requires case insensitive match on v
                    for s in source_names:
                        if self.normalize(s) == self.normalize(v):
                            best_match = s
                            break
        
        self._cache[cache_key] = best_match
        return best_match
