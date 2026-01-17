"""
ESPN NCAA Basketball API Client (Free)

Fetches NCAAM game data, scores, and team information from ESPN's public API.
No API key required - completely free to use.
"""

import requests
from typing import List, Dict, Optional
from datetime import datetime

class ESPNNCAAClient:
    """Free ESPN NCAA Basketball API client"""
    
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        })
    
    def get_scoreboard(self, date: Optional[str] = None) -> Dict:
        """
        Get scoreboard for a specific date
        
        Args:
            date: Date in YYYYMMDD format (e.g., "20260117"). Defaults to today.
            
        Returns:
            Dict with games, scores, and status
        """
        url = f"{self.BASE_URL}/scoreboard"
        params = {}
        if date:
            params['dates'] = date
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[ESPN] Error fetching scoreboard: {e}")
            return {}
    
    def get_team_info(self, team_id: str) -> Dict:
        """
        Get detailed team information
        
        Args:
            team_id: ESPN team ID
            
        Returns:
            Dict with team details, roster, stats
        """
        url = f"{self.BASE_URL}/teams/{team_id}"
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[ESPN] Error fetching team {team_id}: {e}")
            return {}
    
    def get_game_injuries(self, game_id: str) -> List[Dict]:
        """
        Get injury report for a specific game
        
        Args:
            game_id: ESPN game ID
            
        Returns:
            List of injured players with status
        """
        # ESPN includes injuries in the game summary
        url = f"{self.BASE_URL}/summary"
        params = {'event': game_id}
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            injuries = []
            
            # Extract injuries from both teams
            for team_key in ['home', 'away']:
                team_data = data.get('boxscore', {}).get('teams', [])
                for team in team_data:
                    if team.get('homeAway') == team_key:
                        for player in team.get('statistics', [{}])[0].get('athletes', []):
                            if player.get('injured'):
                                injuries.append({
                                    'name': player.get('athlete', {}).get('displayName'),
                                    'team': team.get('team', {}).get('displayName'),
                                    'status': 'Injured',
                                    'position': player.get('athlete', {}).get('position', {}).get('abbreviation')
                                })
            
            return injuries
            
        except Exception as e:
            print(f"[ESPN] Error fetching injuries for game {game_id}: {e}")
            return []
    
    def find_team_by_name(self, team_name: str) -> Optional[str]:
        """
        Find ESPN team ID by name
        
        Args:
            team_name: Team name (e.g., "Duke Blue Devils")
            
        Returns:
            ESPN team ID or None
        """
        # Get today's scoreboard to find teams
        scoreboard = self.get_scoreboard()
        
        for event in scoreboard.get('events', []):
            for competition in event.get('competitions', []):
                for competitor in competition.get('competitors', []):
                    team = competitor.get('team', {})
                    if team_name.lower() in team.get('displayName', '').lower():
                        return team.get('id')
        
        return None
    
    def get_game_context(self, home_team: str, away_team: str) -> Dict:
        """
        Get comprehensive game context including injuries and recent form
        
        Args:
            home_team: Home team name
            away_team: Away team name
            
        Returns:
            Dict with injuries, records, recent games
        """
        scoreboard = self.get_scoreboard()
        
        context = {
            'home_team': home_team,
            'away_team': away_team,
            'injuries': [],
            'home_record': None,
            'away_record': None,
            'game_notes': []
        }
        
        # Find the game
        for event in scoreboard.get('events', []):
            for competition in event.get('competitions', []):
                competitors = competition.get('competitors', [])
                
                # Check if this is the right matchup
                team_names = [c.get('team', {}).get('displayName', '') for c in competitors]
                if any(home_team.lower() in name.lower() for name in team_names) and \
                   any(away_team.lower() in name.lower() for name in team_names):
                    
                    # Extract records
                    for competitor in competitors:
                        team_name = competitor.get('team', {}).get('displayName')
                        record = competitor.get('records', [{}])[0].get('summary')
                        
                        if home_team.lower() in team_name.lower():
                            context['home_record'] = record
                        else:
                            context['away_record'] = record
                    
                    # Get injuries
                    game_id = event.get('id')
                    if game_id:
                        context['injuries'] = self.get_game_injuries(game_id)
                    
                    # Get game notes
                    notes = competition.get('notes', [])
                    context['game_notes'] = [n.get('headline') for n in notes if n.get('headline')]
                    
                    break
        
        return context
    
    def summarize_context(self, context: Dict) -> str:
        """
        Generate human-readable summary of game context
        
        Args:
            context: Output from get_game_context
            
        Returns:
            Summary string
        """
        parts = []
        
        if context.get('home_record'):
            parts.append(f"{context['home_team']}: {context['home_record']}")
        if context.get('away_record'):
            parts.append(f"{context['away_team']}: {context['away_record']}")
        
        injury_count = len(context.get('injuries', []))
        if injury_count > 0:
            parts.append(f"{injury_count} injury report(s)")
        
        if context.get('game_notes'):
            parts.append(f"{len(context['game_notes'])} game note(s)")
        
        return " | ".join(parts) if parts else "No additional context"


# Example usage
if __name__ == "__main__":
    client = ESPNNCAAClient()
    
    # Get today's scoreboard
    scoreboard = client.get_scoreboard()
    print(f"Found {len(scoreboard.get('events', []))} games today")
    
    # Get context for a specific game
    if scoreboard.get('events'):
        event = scoreboard['events'][0]
        competitors = event['competitions'][0]['competitors']
        home = competitors[0]['team']['displayName']
        away = competitors[1]['team']['displayName']
        
        context = client.get_game_context(home, away)
        print(f"\nContext: {client.summarize_context(context)}")
        
        if context['injuries']:
            print("\nInjuries:")
            for injury in context['injuries']:
                print(f"  - {injury['name']} ({injury['team']}): {injury['status']}")
