"""
KenPom Client for Ensemble Model

Fetches KenPom efficiency ratings from database and calculates adjustments
"""

from typing import Dict, Optional
from src.database import get_db_connection, _exec
from src.utils.team_matcher import TeamMatcher

class KenPomClient:
    """Client for KenPom efficiency data"""
    
    def __init__(self):
        self.matcher = TeamMatcher()
    
    def get_team_rating(self, team_name: str) -> Optional[Dict]:
        """
        Get KenPom rating for a team
        
        Args:
            team_name: Team name to lookup
            
        Returns:
            Dict with adj_em, adj_o, adj_d, adj_t or None
        """
        matched_name = self.matcher.find_source_name(team_name, "kenpom_ratings", "team_name")
        if not matched_name:
            return None

        with get_db_connection() as conn:
            query = """
            SELECT team_name, rank, adj_em, adj_o, adj_d, adj_t
            FROM kenpom_ratings
            WHERE team_name = %s
            LIMIT 1
            """
            cursor = _exec(conn, query, (matched_name,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'team': row['team_name'],
                    'rank': row['rank'],
                    'adj_em': row['adj_em'],
                    'adj_o': row['adj_o'],
                    'adj_d': row['adj_d'],
                    'adj_t': row['adj_t']
                }
            
            return None
    
    def calculate_kenpom_adjustment(self, home_team: str, away_team: str) -> Dict:
        """
        Calculate spread/total adjustment based on KenPom ratings
        
        Logic:
        - AdjEM difference → spread adjustment
        - AdjT average → total adjustment
        
        Args:
            home_team: Home team name
            away_team: Away team name
            
        Returns:
            Dict with spread_adj, total_adj, summary
        """
        home_rating = self.get_team_rating(home_team)
        away_rating = self.get_team_rating(away_team)
        
        if not home_rating or not away_rating:
            return {
                'spread_adj': 0.0,
                'total_adj': 0.0,
                'summary': 'KenPom data not available'
            }
        
        # Spread adjustment based on AdjEM difference
        # AdjEM is already adjusted for home court (~3.5 pts)
        em_diff = home_rating['adj_em'] - away_rating['adj_em']
        spread_adj = em_diff * 0.1  # 10 pt AdjEM diff = 1 pt spread
        
        # Total adjustment based on tempo
        avg_tempo = (home_rating['adj_t'] + away_rating['adj_t']) / 2
        baseline_tempo = 68.0  # National average
        total_adj = (avg_tempo - baseline_tempo) * 0.3  # Faster tempo = higher total
        
        summary = f"KenPom: {home_rating['team']} (#{home_rating['rank']}) vs {away_rating['team']} (#{away_rating['rank']})"
        
        return {
            'spread_adj': round(spread_adj, 1),
            'total_adj': round(total_adj, 1),
            'summary': summary,
            'home_adj_em': home_rating['adj_em'],
            'away_adj_em': away_rating['adj_em']
        }


# Example usage
if __name__ == "__main__":
    client = KenPomClient()
    
    # Test lookup
    duke = client.get_team_rating("Duke")
    if duke:
        print(f"Duke: #{duke['rank']} - AdjEM {duke['adj_em']:.2f}")
    
    # Test adjustment
    adj = client.calculate_kenpom_adjustment("Duke", "North Carolina")
    print(f"\nKenPom Adjustment:")
    print(f"  Spread: {adj['spread_adj']:+.1f} pts")
    print(f"  Total: {adj['total_adj']:+.1f} pts")
    print(f"  {adj['summary']}")
