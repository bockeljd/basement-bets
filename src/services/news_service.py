"""
News Fetching Service for Game Context

Fetches relevant news articles about teams to capture:
- Injury reports
- Lineup changes  
- Coaching changes
- Team momentum/trends
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

class NewsService:
    """Fetch news articles relevant to upcoming games"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize news service
        
        Args:
            api_key: News API key (optional, uses env var if not provided)
        """
        import os
        self.api_key = api_key or os.environ.get('NEWS_API_KEY')
        self.base_url = "https://newsapi.org/v2/everything"
    
    def fetch_team_news(self, team_name: str, days_back: int = 3) -> List[Dict]:
        """
        Fetch recent news articles about a team
        
        Args:
            team_name: Full team name (e.g., "Duke Blue Devils")
            days_back: How many days back to search
            
        Returns:
            List of news articles with title, description, url, publishedAt
        """
        if not self.api_key:
            print("[NEWS] No API key configured, skipping news fetch")
            return []
        
        # Calculate date range
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        
        # Build query
        query = f'"{team_name}" AND (injury OR lineup OR suspended OR "out for")'
        
        params = {
            'q': query,
            'from': from_date.strftime('%Y-%m-%d'),
            'to': to_date.strftime('%Y-%m-%d'),
            'language': 'en',
            'sortBy': 'relevancy',
            'pageSize': 5,
            'apiKey': self.api_key
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            articles = data.get('articles', [])
            return [{
                'title': a.get('title'),
                'description': a.get('description'),
                'url': a.get('url'),
                'published_at': a.get('publishedAt'),
                'source': a.get('source', {}).get('name')
            } for a in articles]
            
        except Exception as e:
            print(f"[NEWS] Error fetching news for {team_name}: {e}")
            return []
    
    def fetch_game_context(self, home_team: str, away_team: str) -> Dict:
        """
        Fetch news context for both teams in a matchup
        
        Args:
            home_team: Home team name
            away_team: Away team name
            
        Returns:
            Dict with 'home_news' and 'away_news' lists
        """
        home_news = self.fetch_team_news(home_team)
        away_news = self.fetch_team_news(away_team)
        
        return {
            'home_team': home_team,
            'away_team': away_team,
            'home_news': home_news,
            'away_news': away_news,
            'has_injury_news': any('injury' in (a.get('title', '') + a.get('description', '')).lower() 
                                   for a in home_news + away_news)
        }
    
    def summarize_impact(self, game_context: Dict) -> str:
        """
        Generate a brief summary of news impact
        
        Args:
            game_context: Output from fetch_game_context
            
        Returns:
            Human-readable summary string
        """
        home_count = len(game_context.get('home_news', []))
        away_count = len(game_context.get('away_news', []))
        
        if home_count == 0 and away_count == 0:
            return "No recent injury/lineup news"
        
        parts = []
        if home_count > 0:
            parts.append(f"{home_count} {game_context['home_team']} updates")
        if away_count > 0:
            parts.append(f"{away_count} {game_context['away_team']} updates")
        
        return " | ".join(parts)


# Example usage
if __name__ == "__main__":
    service = NewsService()
    context = service.fetch_game_context("Duke Blue Devils", "North Carolina Tar Heels")
    
    print(f"Home News ({len(context['home_news'])} articles):")
    for article in context['home_news']:
        print(f"  - {article['title']}")
    
    print(f"\nAway News ({len(context['away_news'])} articles):")
    for article in context['away_news']:
        print(f"  - {article['title']}")
    
    print(f"\nSummary: {service.summarize_impact(context)}")
