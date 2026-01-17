"""
Season Statistics Client for NCAAM Teams

Fetches current season stats (W/L, PPG, recent form) from ESPN API
"""

from typing import Dict, Optional
from src.services.espn_ncaa_client import ESPNNCAAClient

class SeasonStatsClient:
    """Fetch current season statistics for NCAAM teams"""
    
    def __init__(self):
        self.espn_client = ESPNNCAAClient()
    
    def get_team_season_stats(self, team_name: str) -> Dict:
        """
        Get current season statistics for a team
        
        Args:
            team_name: Team name (e.g., "Duke Blue Devils")
            
        Returns:
            Dict with wins, losses, ppg, recent_form, etc.
        """
        # Use ESPN scoreboard to find team
        scoreboard = self.espn_client.get_scoreboard()
        
        for event in scoreboard.get('events', []):
            for competition in event.get('competitions', []):
                for competitor in competition.get('competitors', []):
                    team = competitor.get('team', {})
                    
                    if team_name.lower() in team.get('displayName', '').lower():
                        # Extract stats
                        records = competitor.get('records', [])
                        stats = competitor.get('statistics', [])
                        
                        # Parse record (e.g., "18-1")
                        record_str = records[0].get('summary', '0-0') if records else '0-0'
                        wins, losses = map(int, record_str.split('-'))
                        
                        return {
                            'team_name': team.get('displayName'),
                            'wins': wins,
                            'losses': losses,
                            'win_pct': wins / (wins + losses) if (wins + losses) > 0 else 0.5,
                            'record': record_str,
                            'rank': competitor.get('curatedRank', {}).get('current'),
                            'home_away': competitor.get('homeAway')
                        }
        
        # Default if not found
        return {
            'team_name': team_name,
            'wins': 0,
            'losses': 0,
            'win_pct': 0.5,
            'record': '0-0',
            'rank': None,
            'home_away': None
        }
    
    def calculate_season_adjustment(self, home_team: str, away_team: str) -> Dict:
        """
        Calculate spread/total adjustment based on season stats
        
        Logic:
        - Win % difference: 10% win rate diff = ~1 pt spread adjustment
        - Ranking: Top 10 team gets +0.5 to +1.5 pt boost
        - Home court: Already in base model, don't double-count
        
        Args:
            home_team: Home team name
            away_team: Away team name
            
        Returns:
            Dict with spread_adj, total_adj, summary
        """
        home_stats = self.get_team_season_stats(home_team)
        away_stats = self.get_team_season_stats(away_team)
        
        # Win % adjustment
        win_pct_diff = home_stats['win_pct'] - away_stats['win_pct']
        spread_adj = win_pct_diff * 10.0  # 10% diff = 1 pt
        
        # Ranking boost (if team is ranked)
        if home_stats['rank'] and home_stats['rank'] <= 10:
            spread_adj += 0.5
        if away_stats['rank'] and away_stats['rank'] <= 10:
            spread_adj -= 0.5
        
        # Total adjustment: better teams = higher scoring
        avg_win_pct = (home_stats['win_pct'] + away_stats['win_pct']) / 2
        total_adj = (avg_win_pct - 0.5) * 4.0  # 60% win teams = +0.4 pts
        
        summary = f"{home_stats['record']} vs {away_stats['record']}"
        
        return {
            'spread_adj': round(spread_adj, 1),
            'total_adj': round(total_adj, 1),
            'summary': summary,
            'home_win_pct': home_stats['win_pct'],
            'away_win_pct': away_stats['win_pct']
        }


# Example usage
if __name__ == "__main__":
    client = SeasonStatsClient()
    
    # Get season stats
    duke_stats = client.get_team_season_stats("Duke Blue Devils")
    print(f"Duke: {duke_stats['record']} ({duke_stats['win_pct']:.1%})")
    
    # Calculate adjustment
    adj = client.calculate_season_adjustment("Duke Blue Devils", "North Carolina Tar Heels")
    print(f"\nAdjustment: Spread {adj['spread_adj']:+.1f}, Total {adj['total_adj']:+.1f}")
    print(f"Summary: {adj['summary']}")
