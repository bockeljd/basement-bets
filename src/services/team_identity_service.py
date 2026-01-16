import uuid
from typing import Optional, Dict, Tuple
import re
import os
import sys

# Ensure root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Adjust imports based on project structure
try:
    from src.database import get_db_connection, _exec
except ImportError:
    from database import get_db_connection, _exec

class TeamIdentityService:
    """
    Manages team identity resolution, Aliases, and Provider Maps.
    """
    
    def __init__(self):
        # Cache: (provider, provider_team_id) -> canonical_team_id
        self._provider_cache: Dict[Tuple[str, str], str] = {}
        # Alias Cache: normalized_alias -> canonical_team_id
        self._alias_cache: Dict[str, str] = {}
        
    def _normalize_name(self, name: str) -> str:
        """
        Normalize team name for alias storage/lookup.
        Lower case, strip special chars.
        """
        if not name: return ""
        # Remove punctuation, extra spaces, lower case
        return re.sub(r'[^a-z0-9\s]', '', name.lower()).strip()

    def get_or_create_team(self, league: str, provider: str, provider_team_id: str, provider_team_name: str, abbreviation: str = None) -> str:
        """
        Idempotent Get or Create.
        1. Check Cache.
        2. Check DB Map.
        3. If missing, Create Team + Map + Alias.
        4. Return Canonical ID.
        """
        # 1. Cache
        cache_key = (provider, provider_team_id)
        if cache_key in self._provider_cache:
            return self._provider_cache[cache_key]

        canonical_id = None
        
        # 2. DB Lookups
        with get_db_connection() as conn:
            # Check Map
            query_map = "SELECT team_id FROM team_provider_map WHERE provider = :p AND provider_team_id = :pid AND league = :l"
            cursor = _exec(conn, query_map, {"p": provider, "pid": provider_team_id, "l": league})
            row = cursor.fetchone()
            
            if row:
                canonical_id = row[0]
            else:
                # 3. Create New
                canonical_id = str(uuid.uuid4())
                
                # Insert Team
                query_team = """
                INSERT INTO teams (id, league, name, abbreviation)
                VALUES (:id, :league, :name, :abbr)
                """
                _exec(conn, query_team, {
                    "id": canonical_id,
                    "league": league,
                    "name": provider_team_name,
                    "abbr": abbreviation
                })
                
                # Insert Map
                query_map_insert = """
                INSERT INTO team_provider_map (team_id, provider, provider_team_id, provider_team_name, league)
                VALUES (:tid, :p, :pid, :pname, :league)
                """
                _exec(conn, query_map_insert, {
                    "tid": canonical_id,
                    "p": provider,
                    "pid": provider_team_id,
                    "pname": provider_team_name,
                    "league": league
                })
                
                # Insert Alias (Auto)
                normalized_alias = self._normalize_name(provider_team_name)
                if normalized_alias:
                    query_alias = """
                    INSERT INTO team_aliases (team_id, alias, source)
                    VALUES (:tid, :alias, 'auto')
                    ON CONFLICT(team_id, alias) DO NOTHING
                    """
                    _exec(conn, query_alias, {"tid": canonical_id, "alias": normalized_alias})
                    
                conn.commit()
                # print(f"[Identity] Created new team: {provider_team_name} ({canonical_id})")

        # Update Cache
        self._provider_cache[cache_key] = canonical_id
        return canonical_id

    def get_team_by_name(self, name: str, league: str) -> Optional[str]:
        """
        Lookup team by canonical name or alias.
        """
        with get_db_connection() as conn:
            # 1. Check Canonical Name
            # Simple Exact/Lower match
            row = _exec(conn, "SELECT id FROM teams WHERE league = :l AND LOWER(name) = LOWER(:n)", 
                       {"l": league, "n": name}).fetchone()
            if row:
                return row[0]
                
            # 2. Check Aliases
            row = _exec(conn, """
                SELECT t.id FROM teams t
                JOIN team_aliases a ON t.id = a.team_id
                WHERE t.league = :l AND LOWER(a.alias) = LOWER(:n)
            """, {"l": league, "n": name}).fetchone()
            if row:
                return row[0]
                
        return None

if __name__ == "__main__":
    # Smoke Test
    svc = TeamIdentityService()
    tid = svc.get_or_create_team("NFL", "TEST_PROVIDER", "101", "Test Team Falcons", "TTF")
    print(f"Team ID: {tid}")
    tid2 = svc.get_or_create_team("NFL", "TEST_PROVIDER", "101", "Test Team Falcons", "TTF")
    print(f"Team ID (2nd call): {tid2}")
    assert tid == tid2
    print("Smoke Test Passed.")
