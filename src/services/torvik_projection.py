import os
from datetime import datetime
from typing import Dict, Optional
from src.database import get_db_connection, _exec
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
        self._metrics_cache = {}
        self._official_cache = {}

    def get_projection(self, home_team: str, away_team: str, date: str = None, conn=None) -> Dict:
        """
        Main entry point for "Torvik View".
        1. Try to fetch official Torvik projection for the day.
        2. If missing, compute a projection from latest metrics.
        """
        if not date:
            date = datetime.now().strftime("%Y%m%d")
            
        # 1. Official Projection Fetch (prefer cached DB ingest)
        official_projs = self._fetch_official_from_db(date, conn=conn)

        # In backtests, avoid network calls; fall back to computed projections when DB cache missing.
        no_net = str(os.getenv('BACKTEST_NO_NETWORK', '')).strip() not in ('', '0', 'false', 'False')
        if (not official_projs) and (not no_net):
            official_projs = self.bt_client.fetch_daily_projections(date)

        # Match by name (Torvik uses specific naming)
        h_proj = self._find_projection(home_team, official_projs)

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
        return self.compute_torvik_projection(home_team, away_team, date=date)

    def _fetch_official_from_db(self, date_yyyymmdd: str, conn=None) -> Optional[Dict]:
        """Load official Torvik schedule JSON from DB if present."""
        if date_yyyymmdd in self._official_cache:
            return self._official_cache[date_yyyymmdd]

        if conn:
            return self._exec_fetch_official(conn, date_yyyymmdd)
        else:
            with get_db_connection() as c:
                return self._exec_fetch_official(c, date_yyyymmdd)

    def _exec_fetch_official(self, conn, date_yyyymmdd):
        try:
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

        self._official_cache[date_yyyymmdd] = projections if projections else None
        return self._official_cache[date_yyyymmdd]


    def _find_projection(self, team_name: str, projections: Dict) -> Optional[Dict]:

        """
        Fuzzy match team_name against projection keys.
        """
        if not team_name: return None
        if not projections: return None
        
        # 1. Exact Match
        if team_name in projections:
            return projections[team_name]
            
        # 2. Fuzzy Match (Keys are short names like 'Xavier' or 'Michigan St.')
        # Normalize: 'St.' -> 'State', remove dots, lower
        
        def normalize(s):
            s = s.lower().replace('.', '')
            # Replace " st" at end of string with " state"
            if s.endswith(' st'): 
                s = s[:-3] + ' state'
            return s.strip()

        norm_input = normalize(team_name)
        
        candidates = []
        for key, data in projections.items():
            norm_key = normalize(key)
            
            # Check containment in either direction
            # "Michigan St." (norm: michigan state) in "Michigan State Spartans" (norm: michigan state spartans) -> YES
            # "Xavier" in "Xavier Musketeers" -> YES
            
            if norm_key in norm_input:
                 candidates.append((key, data, len(norm_key)))
            elif norm_input in norm_key: # Rare, but possible if Torvik has longer name
                 candidates.append((key, data, len(norm_input)))

        if candidates:
            # Pick longest MATCH LENGTH (closest fit)
            candidates.sort(key=lambda x: x[2], reverse=True)
            return candidates[0][1]
            
        return None

    def get_matchup_team_stats(self, home_team: str, away_team: str, date: str = None) -> Dict:
        """Return best-available Torvik team efficiency stats for both teams.

        These are used for UI explanations and basic game-script reasoning.
        """
        h = self._get_latest_metrics(home_team, date=date)
        a = self._get_latest_metrics(away_team, date=date)
        if not h or not a:
            return {
                "home": h,
                "away": a,
                "game_tempo": None,
                "notes": "Missing team efficiency metrics"
            }
        # Be careful: DB rows may include keys with explicit NULLs (None), so `.get(key, 0)`
        # can still return None. Coalesce to 0.0 before arithmetic to avoid
        # `TypeError: unsupported operand type(s) for +: 'NoneType' and 'NoneType'`.
        h_tempo = h.get('adj_tempo') or 0.0
        a_tempo = a.get('adj_tempo') or 0.0
        game_tempo = (float(h_tempo) + float(a_tempo)) / 2.0

        # If tempo is missing in DB for one/both teams, fall back to a sane NCAA baseline
        # so downstream projection math never sees None.
        if not game_tempo:
            game_tempo = 68.0

        return {
            "home": h,
            "away": a,
            "game_tempo": round(game_tempo, 1),
            "notes": None
        }

    def compute_torvik_projection(self, home_team: str, away_team: str, date: str = None) -> Dict:
        """Heuristic projection using raw efficiency (AdjOE, AdjDE, AdjTempo).
        Score = (OE_home * DE_away) / Avg_Eff * Tempo / 100.
        """
        stats = self.get_matchup_team_stats(home_team, away_team, date=date)
        h = stats.get('home')
        a = stats.get('away')
        
        if not h or not a:
             return {"margin": 0, "total": 145, "lean": "No Data"}
             
        tempo = stats.get('game_tempo') or 68.0
        
        # Calculate scores (defensive None handling)
        # Home Score = (HomeAdjOE * AwayAdjDE) / LeagueAvg * (Tempo/100)
        eff_factor = float(self.LEAGUE_AVG_EFF)
        h_off = float(h.get('adj_off') or 0.0)
        h_def = float(h.get('adj_def') or 0.0)
        a_off = float(a.get('adj_off') or 0.0)
        a_def = float(a.get('adj_def') or 0.0)

        # If core metrics are missing, we cannot compute a projection.
        if (h_off <= 0.0) or (h_def <= 0.0) or (a_off <= 0.0) or (a_def <= 0.0):
            return {"margin": 0, "total": 145, "lean": "No Data"}

        h_score = (h_off * a_def / eff_factor) * (tempo / 100.0)
        a_score = (a_off * h_def / eff_factor) * (tempo / 100.0)
        
        # HCA (Home Court Advantage). Torvik uses ~3 pts?
        # Let's assume stats include HCA? No, raw efficiency is neutral.
        # Add standard HCA of ~3.2 points (average).
        h_score += 3.2
        
        total = h_score + a_score
        spread = h_score - a_score # Home margin (e.g. +5 means Home by 5)
        # Note: spread in betting is opposite.
        
        return {
            "margin": spread,
            "total": total,
            "projected_score": f"{int(a_score)}-{int(h_score)}",
            "lean": "Computed from Raw Efficiency"
        }

    def _get_latest_metrics(self, team_name: str, date: str = None, conn=None) -> Optional[Dict]:
        """Fetch latest daily metrics for a team from DB."""
        cache_key = f"{team_name}_{date}"
        if cache_key in self._metrics_cache:
            return self._metrics_cache[cache_key]

        # Find canonical name
        t = self.matcher.find_source_name(team_name, "bt_team_metrics_daily", "team_text")
        if not t:
            self._metrics_cache[cache_key] = None
            return None

        if conn:
            return self._exec_metrics_query(conn, t, date, cache_key)
        else:
            with get_db_connection() as c:
                return self._exec_metrics_query(c, t, date, cache_key)

    def _exec_metrics_query(self, conn, t, date, cache_key):
        # Build query
        # If date provided, find latest metrics ON OR BEFORE that date.
        
        params = {"t": t}
        date_clause = ""
        if date:
            date_clause = "AND date <= :date"
            params["date"] = date
            
        # NOTE: schema can vary across environments; some deployments only have
        # adj_off/adj_def/adj_tempo/luck. Query defensively.
        query_full = f"""
        SELECT adj_off, adj_def, adj_tempo, luck, continuity, torvik_rank, record
        FROM bt_team_metrics_daily
        WHERE team_text = :t {date_clause}
        ORDER BY date DESC LIMIT 1
        """

        query_min = f"""
        SELECT adj_off, adj_def, adj_tempo, luck
        FROM bt_team_metrics_daily
        WHERE team_text = :t {date_clause}
        ORDER BY date DESC LIMIT 1
        """
        
        try:
            row = _exec(conn, query_full, params).fetchone()
        except Exception:
            row = _exec(conn, query_min, params).fetchone()
            
        if row:
            res = dict(row)
            self._metrics_cache[cache_key] = res
            return res
        self._metrics_cache[cache_key] = None
        return None

if __name__ == "__main__":
    svc = TorvikProjectionService()
    # Simple test with hypothetical teams
    res = svc.compute_torvik_projection("Duke", "Kansas")
    print(res)
