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
    
    def __init__(self):
        self.bt_client = BartTorvikClient()
        self.identity = TeamIdentityService()

    def get_projection(self, home_team: str, away_team: str, date: str = None) -> Dict:
        """
        Main entry point for "Torvik View".
        1. Try to fetch official Torvik projection for the day.
        2. If missing, compute a projection from latest metrics.
        """
        if not date:
            date = datetime.now().strftime("%Y%m%d")
            
        # 1. Official Projection Fetch
        official_projs = self.bt_client.fetch_daily_projections(date)
        # Match by name (Torvik uses specific naming)
        # Note: we might need a better matcher here for fuzzy names
        # For now, try direct match or normalized alias
        h_proj = official_projs.get(home_team)
        a_proj = official_projs.get(away_team)
        
        if h_proj:
            return {
                "source": "official",
                "margin": -h_proj['spread'], # Torvik spread is usually Home relative (e.g. -5 means Home favored by 5). We want Home Margin > 0.
                "official_margin": -float(h_proj['spread']),
                "total": float(h_proj['total']),
                "projected_score": h_proj['projected_score'],
                "lean": "Official torvik projection"
            }

        # 2. Heuristic Computation (The "Torvik thinks" backup)
        return self.compute_torvik_projection(home_team, away_team)

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
        query = """
        SELECT adj_off, adj_def, adj_tempo 
        FROM bt_team_metrics_daily 
        WHERE team_text = :t 
        ORDER BY date DESC LIMIT 1
        """
        with get_db_connection() as conn:
            row = _exec(conn, query, {"t": team_name}).fetchone()
            if row:
                return dict(row)
        return None

if __name__ == "__main__":
    svc = TorvikProjectionService()
    # Simple test with hypothetical teams
    res = svc.compute_torvik_projection("Duke", "Kansas")
    print(res)
