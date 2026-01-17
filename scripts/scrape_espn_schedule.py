"""
ESPN NCAAM Schedule Scraper

Scrapes complete NCAAM basketball schedule (historical and future games)
from ESPN's public API
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from src.services.espn_ncaa_client import ESPNNCAAClient
from src.database import get_db_connection, _exec

class ESPNScheduleScraper:
    """Scrape NCAAM schedule from ESPN"""
    
    def __init__(self):
        self.espn_client = ESPNNCAAClient()
    
    def scrape_date_range(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Scrape all games in a date range
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            
        Returns:
            List of game dicts with scores, teams, dates
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        all_games = []
        current = start
        
        while current <= end:
            date_str = current.strftime('%Y%m%d')
            print(f"[ESPN] Scraping {current.strftime('%Y-%m-%d')}...")
            
            scoreboard = self.espn_client.get_scoreboard(date=date_str)
            events = scoreboard.get('events', [])
            
            for event in events:
                game = self._parse_event(event)
                if game:
                    all_games.append(game)
            
            print(f"[ESPN]   Found {len(events)} games")
            current += timedelta(days=1)
        
        return all_games
    
    def _parse_event(self, event: Dict) -> Optional[Dict]:
        """Parse an ESPN event into game dict"""
        try:
            game_id = event.get('id')
            name = event.get('name', '')
            date = event.get('date')
            
            competition = event.get('competitions', [{}])[0]
            competitors = competition.get('competitors', [])
            
            if len(competitors) < 2:
                return None
            
            # Determine home/away
            home = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            
            if not home or not away:
                # Fallback: first is home, second is away
                home = competitors[0]
                away = competitors[1]
            
            home_team = home.get('team', {}).get('displayName', '')
            away_team = away.get('team', {}).get('displayName', '')
            
            # Scores (may be null for future games)
            home_score = home.get('score')
            away_score = away.get('score')
            
            # Status
            status = competition.get('status', {})
            status_type = status.get('type', {}).get('name', 'scheduled')
            completed = status_type == 'STATUS_FINAL'
            
            return {
                'game_id': game_id,
                'date': date,
                'home_team': home_team,
                'away_team': away_team,
                'home_score': float(home_score) if home_score else None,
                'away_score': float(away_score) if away_score else None,
                'completed': completed,
                'status': status_type
            }
            
        except Exception as e:
            print(f"[ESPN] Error parsing event: {e}")
            return None
    
    def save_to_database(self, games: List[Dict]):
        """
        Save scraped games to database
        
        Args:
            games: List of game dicts
        """
        with get_db_connection() as conn:
            # Create table if not exists
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS espn_schedule (
                    game_id TEXT PRIMARY KEY,
                    date TIMESTAMP,
                    home_team TEXT,
                    away_team TEXT,
                    home_score REAL,
                    away_score REAL,
                    completed BOOLEAN,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert/update games
            inserted = 0
            for game in games:
                _exec(conn, """
                    INSERT INTO espn_schedule 
                    (game_id, date, home_team, away_team, home_score, away_score, completed, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (game_id) 
                    DO UPDATE SET
                        home_score = EXCLUDED.home_score,
                        away_score = EXCLUDED.away_score,
                        completed = EXCLUDED.completed,
                        status = EXCLUDED.status
                """, (
                    game['game_id'],
                    game['date'],
                    game['home_team'],
                    game['away_team'],
                    game['home_score'],
                    game['away_score'],
                    game['completed'],
                    game['status']
                ))
                inserted += 1
            
            conn.commit()
            print(f"[ESPN] Saved {inserted} games to database")


# Example usage
if __name__ == "__main__":
    scraper = ESPNScheduleScraper()
    
    # Scrape last 30 days
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    print(f"Scraping NCAAM schedule from {start_date} to {end_date}")
    games = scraper.scrape_date_range(start_date, end_date)
    
    print(f"\nTotal games scraped: {len(games)}")
    completed = sum(1 for g in games if g['completed'])
    print(f"Completed games: {completed}")
    print(f"Upcoming games: {len(games) - completed}")
    
    # Save to database
    scraper.save_to_database(games)
    
    # Show sample
    if games:
        print("\nSample completed game:")
        completed_game = next((g for g in games if g['completed']), None)
        if completed_game:
            print(f"  {completed_game['away_team']} @ {completed_game['home_team']}")
            print(f"  Score: {completed_game['away_score']}-{completed_game['home_score']}")
            print(f"  Date: {completed_game['date']}")
