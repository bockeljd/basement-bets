from datetime import datetime
from typing import Dict, Optional
from src.database import get_db_connection, _exec
from src.services.barttorvik import BartTorvikClient
from src.services.team_identity_service import TeamIdentityService

class TorvikProjectionService:
    """
    Computes/Fetches Torvik-style projections for NCAAM games.
    Uses daily team efficiency metrics (AdjOE, AdjDE, AdjTempo).
    """
    
    LEAGUE_AVG_EFF = 106.0  # Approx D1 average efficiency
    
from src.services.barttorvik import BartTorvikClient
from src.services.team_identity_service import TeamIdentityService
from src.utils.team_matcher import TeamMatcher

class TorvikProjectionService:
    """
    Computes/Fetches Torvik-style projections for NCAAM games.
    """
    
    LEAGUE_AVG_EFF = 106.0
    
    def __init__(self):
        self.bt_client = BartTorvikClient()
        self.identity = TeamIdentityService()
        self.matcher = TeamMatcher()

    def get_projection(self, home_team: str, away_team: str, date: str = None) -> Dict:
        """
        Main entry point for "Torvik View".
        1. Try to fetch official Torvik projection for the day.
        2. If missing, compute a projection from latest metrics.
        """
        if not date:
            date = datetime.now().strftime("%Y%m%d")
            
        # 1. Official Projection Fetch (prefer cached DB ingest)
        official_projs = self._fetch_official_from_db(date) or self.bt_client.fetch_daily_projections(date)
        # Match by name (Torvik uses specific naming)
        h_proj = self._find_projection(home_team, official_projs)
        a_proj = self._find_projection(away_team, official_projs)

        if h_proj:
            return {
                "source": "official",
                "margin": -float(h_proj['spread']),
                "official_margin": -float(h_proj['spread']),
                "total": float(h_proj['total']),
                "projected_score": h_proj.get('projected_score') or None,
                "lean": "Official Torvik projection (cached)" if self._fetch_official_from_db(date) else "Official Torvik projection"
            }

        # 2. Heuristic Computation (The "Torvik thinks" backup)
        return self.compute_torvik_projection(home_team, away_team)

    def _fetch_official_from_db(self, date_yyyymmdd: str) -> Optional[Dict]:
        """Load official Torvik schedule JSON from DB if present.

        Returns a projections dict keyed by team name (like BartTorvikClient.fetch_daily_projections).
        """
        try:
            with get_db_connection() as conn:
                row = _exec(conn, """
                    SELECT payload_json
                    FROM bt_daily_schedule_raw
                    WHERE date = %s AND status = 'OK' AND payload_json IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (date_yyyymmdd,)).fetchone()
                if not row:
                    return None
                payload = row.get('payload_json') if isinstance(row, dict) else row[0]
        except Exception:
            return None

        if not payload or not isinstance(payload, list):
            return None

        projections = {}
        for item in payload:
            try:
                away = item.get('away')
                home = item.get('home')
                if not away or not home:
                    continue

                # Our selenium ingest stores home-relative spread as `home_spread`.
                # Keep the older key name `spread` to align with TorvikProjectionService.
                home_spread = item.get('home_spread')
                if home_spread is None:
                    home_spread = item.get('spread')

                total = item.get('total')
                if total is None:
                    # fallback to scores
                    try:
                        total = float(item.get('home_score', 0)) + float(item.get('away_score', 0))
                    except Exception:
                        total = 0.0

                projected_score = None
                if item.get('away_score') is not None and item.get('home_score') is not None:
                    projected_score = f"{item.get('away_score')}-{item.get('home_score')}"

                # Create per-team projection entries. For historical compatibility:
                # - for the away team entry, store opponent=home
                # - store `spread` as the home-relative spread
                proj_base = {
                    "total": float(total) if total else 0.0,
                    "projected_score": projected_score,
                    "spread": float(home_spread) if home_spread is not None else 0.0,
                    "raw_line": item.get('line_text') or str(home_spread),
                }

                projections[away] = {**proj_base, "team": away, "opponent": home}
                projections[home] = {**proj_base, "team": home, "opponent": away}
            except Exception:
                continue

        return projections or None


    def _find_projection(self, team_name: str, projections: Dict) -> Optional[Dict]:

        """
        Fuzzy match team_name against projection keys.
        """
        if not team_name: return None
        
        # 1. Exact Match
        if team_name in projections:
            return projections[team_name]
            
        # 2. Fuzzy Match (Keys are short names like 'Xavier')
        # Check if Key is substring of input (e.g. 'Xavier' in 'Xavier Musketeers')
        norm_input = team_name.lower().replace('.', '').strip()
        
        candidates = []
        for key, data in projections.items():
            norm_key = key.lower().replace('.', '').strip()
            # Check length to avoid 'Iowa' matching 'Iowa State' incorrectly?
            # Torvik name is usually the prefix.
            if norm_key in norm_input:
                 candidates.append((key, data))
        
        if candidates:
            # Pick longest key (e.g. 'Southern Miss' over 'Southern')
            candidates.sort(key=lambda x: len(x[0]), reverse=True)
            return candidates[0][1]
            
        return None

    def get_matchup_team_stats(self, home_team: str, away_team: str) -> Dict:
        """Return best-available Torvik team efficiency stats for both teams.

        These are used for UI explanations and basic game-script reasoning.
        """
        h = self._get_latest_metrics(home_team)
        a = self._get_latest_metrics(away_team)
        if not h or not a:
            return {
                "home": h,
                "away": a,
                "game_tempo": None,
                "notes": "Missing team efficiency metrics"
            }
        game_tempo = (h.get('adj_tempo', 0) + a.get('adj_tempo', 0)) / 2.0
        return {
            "home": h,
            "away": a,
            "game_tempo": round(game_tempo, 1),
            "notes": None
        }

    def compute_torvik_projection(self, home_team: str, away_team: str) -> Dict:
        """
        Compute projection using interaction formula:
        Proj Score = (AdjOE * Opp AdjDE / AvgEff) * (Tempo / 100)
        """
        h_stats = self._get_latest_metrics(home_team)
        a_stats = self._get_latest_metrics(away_team)
        
        if not h_stats or not a_stats:
            return {
                "source": "error",
                "margin": 0,
                "total": 0,
                "projected_score": "N/A",
                "lean": "Missing team efficiency metrics"
            }
            
        # Average Tempo
        game_tempo = (h_stats['adj_tempo'] + a_stats['adj_tempo']) / 2.0
        
        # Home Projection
        h_score = (h_stats['adj_off'] * a_stats['adj_def'] / self.LEAGUE_AVG_EFF) * (game_tempo / 100.0)
        # Away Projection
        a_score = (a_stats['adj_off'] * h_stats['adj_def'] / self.LEAGUE_AVG_EFF) * (game_tempo / 100.0)
        
        margin = h_score - a_score
        total = h_score + a_score
        
        return {
            "source": "computed",
            "margin": round(margin, 1),
            "official_margin": round(margin, 1), # Fallback to computed
            "total": round(total, 1),
            "projected_score": f"{round(a_score, 1)}-{round(h_score, 1)}",
            "lean": "Torvik-style computed from efficiencies"
        }

    def _get_latest_metrics(self, team_name: str) -> Optional[Dict]:
        """
        Fetch latest metrics from bt_team_metrics_daily.
        """
        # Normalize Name via Matcher
        matched_name = self.matcher.find_source_name(team_name, "bt_team_metrics_daily", "team_text")
        if not matched_name:
            print(f"[Torvik] No match found for '{team_name}'")
            return None

        query = """
        SELECT adj_off, adj_def, adj_tempo 
        FROM bt_team_metrics_daily 
        WHERE team_text = :t 
        ORDER BY date DESC LIMIT 1
        """
        with get_db_connection() as conn:
            row = _exec(conn, query, {"t": matched_name}).fetchone()
            if row:
                return dict(row)
        return None

if __name__ == "__main__":
    svc = TorvikProjectionService()
    # Simple test with hypothetical teams
    res = svc.compute_torvik_projection("Duke", "Kansas")
    print(res)
