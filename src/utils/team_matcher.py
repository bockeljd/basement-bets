
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

    # Tokens that indicate a different school if they immediately follow a prefix match
    # (e.g., prevent "Kansas" from matching "Kansas City Roos" or "Kentucky" from matching "Kentucky State Thorobreds").
    _DISAMBIGUATING_NEXT_WORDS = {
        "state", "st", "city", "baptist", "international", "methodist", "valley",
        "tech", "southern", "northern", "eastern", "western", "central", "am",
        "corpus", "pine", "monroe", "martin", "edwardsville", "shore", "christian",
        "poly", "gulf", "atlantic", "pacific", "college", "university", "lutheran",
        "wesleyan", "maritime", "military", "coast", "point", "island",
    }

    def normalize(self, name: str) -> str:
        """Normalize school/event team name for cross-provider matching."""
        if not name:
            return ""
        s = name.lower().strip()
        # Handle parenthetical qualifiers cleanly before stripping punctuation
        s = re.sub(r'\(\s*fl\s*\)', ' fl ', s)
        s = re.sub(r'\(\s*oh\s*\)', ' oh ', s)
        s = re.sub(r'\(\s*md\s*\)', ' md ', s)
        s = re.sub(r'\(\s*pa\s*\)', ' pa ', s)
        s = re.sub(r'\(\s*ny\s*\)', ' ny ', s)
        s = re.sub(r'\(\s*ca\s*\)', ' ca ', s)
        s = re.sub(r'\(\s*mn\s*\)', ' mn ', s)
        # Normalize N.C. / U.S.C. / L.I.U. / St. abbreviations
        s = re.sub(r'\bn\.?\s*c\.?\s+st(ate|\.)?\b', 'nc state', s)
        s = re.sub(r'\bnorth\s+carolina\s+st(ate|\.)?\b', 'nc state', s)
        # Replace hyphens and slashes with spaces so "Maryland-Eastern" -> "maryland eastern"
        s = re.sub(r'[-/]+', ' ', s)
        # Remove remaining non-alphanumeric characters
        s = re.sub(r'[^a-z0-9\s]', '', s)
        tokens = s.split()
        # Convert "st" -> "state" unless it is "st" as in Saint (first token or after "mount")
        norm_tokens = []
        for idx, tok in enumerate(tokens):
            if tok == "st" and idx > 0 and tokens[idx - 1] != "mount":
                norm_tokens.append("state")
            else:
                norm_tokens.append(tok)
        return " ".join(norm_tokens)

    def find_source_name(self, event_team_name: str, source_table: str, source_col: str) -> Optional[str]:
        """
        Find the matching name in the source table.
        Heuristics:
        1. Exact Match (norm)
        2. Canonical Alias Map
        3. Prefix Match with disambiguating-token guard
        """
        cache_key = (event_team_name, source_table)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Use class-level cache for source names to avoid repeated SELECT DISTINCT
        source_cache_key = (source_table, source_col)
        if source_cache_key not in TeamMatcher._source_names_cache:
            with get_db_connection() as conn:
                rows = []
                if source_table == "bt_team_metrics_daily":
                    try:
                        from src.utils.ncaam_season import current_ncaam_season_start_date
                        s_start = current_ncaam_season_start_date()
                        rows = _exec(
                            conn,
                            f"SELECT DISTINCT {source_col} FROM {source_table} WHERE date >= :s_start",
                            {"s_start": s_start},
                        ).fetchall()
                    except Exception:
                        rows = []
                if not rows:
                    rows = _exec(conn, f"SELECT DISTINCT {source_col} FROM {source_table}").fetchall()
                TeamMatcher._source_names_cache[source_cache_key] = [
                    (r[source_col] if isinstance(r, dict) else r[0])
                    for r in rows
                    if (r[source_col] if isinstance(r, dict) else r[0])
                ]

        source_names = TeamMatcher._source_names_cache[source_cache_key]
        norm_event = self.normalize(event_team_name)
        norm_source_map = {self.normalize(s): s for s in source_names}

        best_match = None

        # 1. Exact Match Check
        if norm_event in norm_source_map:
            best_match = norm_source_map[norm_event]

        # 2. Canonical Alias Check (checked before prefix matching so e.g. "Kansas City" -> "UMKC", not "Kansas")
        if not best_match:
            manual_map = {
                "kansas city roos": "UMKC",
                "kansas city": "UMKC",
                "southern methodist mustangs": "SMU",
                "southern methodist": "SMU",
                "california baptist lancers": "Cal Baptist",
                "california baptist": "Cal Baptist",
                "florida international golden panthers": "FIU",
                "florida international": "FIU",
                "omaha mavericks": "Nebraska Omaha",
                "nebraska omaha": "Nebraska Omaha",
                "uic flames": "Illinois Chicago",
                "illinois chicago": "Illinois Chicago",
                "sam houston bearkats": "Sam Houston St.",
                "sam houston state": "Sam Houston St.",
                "central connecticut state blue devils": "Central Connecticut",
                "central connecticut state": "Central Connecticut",
                "texas am cc islanders": "Texas A&M Corpus Chris",
                "texas am corpus christi": "Texas A&M Corpus Chris",
                "southern miss golden eagles": "Southern Miss",
                "southern mississippi": "Southern Miss",
                "southern university jaguars": "Southern",
                "southern university": "Southern",
                "miami fl hurricanes": "Miami FL",
                "miami oh redhawks": "Miami OH",
                "uconn huskies": "Connecticut",
                "ole miss rebels": "Mississippi",
                "ul monroe warhawks": "Louisiana Monroe",
                "ut martin skyhawks": "Tennessee Martin",
                "ut arlington mavericks": "UT Arlington",
                "ut rio grande valley vaqueros": "UT Rio Grande Valley",
                "iu indianapolis jaguars": "IU Indy",
                "iupui jaguars": "IU Indy",
                "long island university sharks": "LIU",
                "liu sharks": "LIU",
                "ualbany great danes": "Albany",
                "albany great danes": "Albany",
                "grambling tigers": "Grambling St.",
                "mcneese cowboys": "McNeese St.",
                "nicholls colonels": "Nicholls St.",
                "southeastern louisiana lions": "Southeastern Louisiana",
                "se louisiana lions": "Southeastern Louisiana",
                "pennsylvania quakers": "Penn",
                "penn quakers": "Penn",
                "st thomas mn tommies": "St. Thomas",
                "saint francis red flash": "Saint Francis",
                "st francis pa red flash": "Saint Francis",
                "queens university royals": "Queens",
            }
            for k, v in manual_map.items():
                if norm_event == k or norm_event.startswith(k + " "):
                    target_norm = self.normalize(v)
                    if target_norm in norm_source_map:
                        best_match = norm_source_map[target_norm]
                        break

        # 3. Substring/Prefix Check with disambiguating-token guard
        if not best_match:
            event_tokens = norm_event.split()
            candidates = []
            for s in source_names:
                norm_s = self.normalize(s)
                if not norm_s:
                    continue
                s_tokens = norm_s.split()
                if event_tokens[:len(s_tokens)] == s_tokens:
                    if len(event_tokens) > len(s_tokens):
                        next_tok = event_tokens[len(s_tokens)]
                        if next_tok in self._DISAMBIGUATING_NEXT_WORDS:
                            continue
                    candidates.append((len(s_tokens), len(norm_s), s))

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
                best_match = candidates[0][2]

        self._cache[cache_key] = best_match
        return best_match
