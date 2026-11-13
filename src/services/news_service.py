"""
News Fetching Service for Game Context

Fetches relevant news articles about teams to capture:
- Injury reports
- Lineup changes  
- Coaching changes
- Team momentum/trends
"""

import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import time
import urllib.parse
import xml.etree.ElementTree as ET

class NewsService:
    """Fetch news articles relevant to upcoming games.

    Primary: NewsAPI (if NEWS_API_KEY is configured)
    Fallback: Google News RSS (no API key)
    """

    _rss_cache: Dict[Tuple[str, int], Tuple[float, List[Dict]]] = {}

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize news service
        
        Args:
            api_key: News API key (optional, uses env var if not provided)
        """
        self.skip_fetch = os.environ.get('BASEMENT_SKIP_NEWS') == '1'
        self.api_key = api_key or os.environ.get('NEWS_API_KEY')
        self.base_url = "https://newsapi.org/v2/everything"
        # RSS defaults
        self.rss_ttl_seconds = int(os.environ.get('NEWS_RSS_TTL_SECONDS', '1800'))  # 30 min
    
    def _fetch_google_news_rss(self, query: str, days_back: int = 3, limit: int = 5) -> List[Dict]:
        """Fetch headlines from Google News RSS for a query (no API key required)."""
        if self.skip_fetch:
            return []
        q = query
        cache_key = (q, int(days_back))
        now = time.time()
        cached = self._rss_cache.get(cache_key)
        if cached and (now - cached[0]) < self.rss_ttl_seconds:
            return cached[1]

        # Google News RSS search
        qs = urllib.parse.quote_plus(q)
        url = f"https://news.google.com/rss/search?q={qs}&hl=en-US&gl=US&ceid=US:en"
        try:
            timeout_s = float(os.environ.get('NEWS_RSS_TIMEOUT_S', '2.0'))
            resp = requests.get(url, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code in (403, 429):
                # Cache brief empty result so serverless requests don't repeatedly stall on blocked RSS.
                self._rss_cache[cache_key] = (now, [])
                return []
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items = root.findall('.//item')

            out: List[Dict] = []
            for it in items[:limit]:
                title = (it.findtext('title') or '').strip()
                link = (it.findtext('link') or '').strip()
                pub = (it.findtext('pubDate') or '').strip()
                source = None
                # Google News titles are often "Headline - Source".
                if ' - ' in title:
                    title, source = title.rsplit(' - ', 1)
                out.append({
                    'title': title,
                    'description': None,
                    'url': link,
                    'published_at': pub,
                    'source': source or 'Google News',
                })

            self._rss_cache[cache_key] = (now, out)
            return out
        except Exception as e:
            print(f"[NEWS] RSS error for query '{query}': {e}")
            self._rss_cache[cache_key] = (now, [])
            return []

    def fetch_team_news(self, team_name: str, days_back: int = 3) -> List[Dict]:
        """
        Fetch recent news articles about a team
        
        Args:
            team_name: Full team name (e.g., "Duke Blue Devils")
            days_back: How many days back to search
            
        Returns:
            List of news articles with title, description, url, publishedAt
        """
        if self.skip_fetch:
            return []
        if not self.api_key:
            # Fallback: Google News RSS
            q = f'"{team_name}" basketball (injury OR lineup OR suspended OR "out for")'
            return self._fetch_google_news_rss(q, days_back=days_back, limit=5)
        
        # Calculate date range
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        
        # Build query
        query = f'"{team_name}" basketball AND (injury OR lineup OR suspended OR "out for")'
        
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
        if self.skip_fetch:
            return {
                'home_team': home_team,
                'away_team': away_team,
                'home_news': [],
                'away_news': [],
                'has_injury_news': False
            }
        home_news = self.fetch_team_news(home_team)
        away_news = self.fetch_team_news(away_team)
        
        return {
            'home_team': home_team,
            'away_team': away_team,
            'home_news': home_news,
            'away_news': away_news,
            'has_injury_news': any(
                'injury' in ((a.get('title') or '') + ' ' + (a.get('description') or '')).lower()
                for a in home_news + away_news
            )
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
