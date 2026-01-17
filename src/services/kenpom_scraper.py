"""
KenPom Data Scraper

Scrapes publicly available efficiency ratings from kenpom.com
Note: Only scrapes public data. Premium data requires subscription.
"""

import requests
from bs4 import BeautifulSoup
import time
from typing import Dict, List, Optional
import re

class KenPomScraper:
    """Scrape publicly available KenPom data"""
    
    BASE_URL = "https://kenpom.com"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def scrape_homepage_rankings(self) -> List[Dict]:
        """
        Scrape the public homepage rankings table
        
        Returns:
            List of team rankings with AdjEM, AdjO, AdjD, AdjT
        """
        print("[KENPOM] Fetching homepage rankings...")
        
        try:
            response = self.session.get(self.BASE_URL, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the main ratings table
            table = soup.find('table', {'id': 'ratings-table'})
            
            if not table:
                print("[KENPOM] Warning: Could not find ratings table (may require login)")
                return []
            
            teams = []
            rows = table.find('tbody').find_all('tr')
            
            for row in rows:
                cols = row.find_all('td')
                
                if len(cols) < 10:
                    continue
                
                try:
                    # Extract data from columns
                    rank = int(cols[0].text.strip())
                    team_link = cols[1].find('a')
                    team_name = team_link.text.strip() if team_link else cols[1].text.strip()
                    
                    # Conference
                    conf = cols[2].text.strip()
                    
                    # Record (W-L)
                    record = cols[3].text.strip()
                    
                    # AdjEM (Adjusted Efficiency Margin)
                    adj_em = float(cols[4].text.strip())
                    
                    # AdjO (Adjusted Offensive Efficiency)
                    adj_o = float(cols[5].text.strip())
                    
                    # AdjD (Adjusted Defensive Efficiency)
                    adj_d = float(cols[7].text.strip())
                    
                    # AdjT (Adjusted Tempo)
                    adj_t = float(cols[9].text.strip())
                    
                    teams.append({
                        'rank': rank,
                        'team': team_name,
                        'conference': conf,
                        'record': record,
                        'adj_em': adj_em,
                        'adj_o': adj_o,
                        'adj_d': adj_d,
                        'adj_t': adj_t
                    })
                    
                except (ValueError, IndexError) as e:
                    print(f"[KENPOM] Error parsing row: {e}")
                    continue
            
            print(f"[KENPOM] Scraped {len(teams)} teams")
            return teams
            
        except Exception as e:
            print(f"[KENPOM] Error scraping homepage: {e}")
            return []
    
    def get_team_by_name(self, team_name: str, teams: List[Dict]) -> Optional[Dict]:
        """
        Find a team by name in the scraped data
        
        Args:
            team_name: Team name to search for
            teams: List of team dicts from scrape_homepage_rankings
            
        Returns:
            Team dict or None
        """
        team_name_lower = team_name.lower()
        
        for team in teams:
            if team_name_lower in team['team'].lower():
                return team
        
        return None
    
    def save_to_database(self, teams: List[Dict]):
        """
        Save scraped data to database
        
        Args:
            teams: List of team dicts
        """
        from src.database import get_db_connection, _exec
        
        with get_db_connection() as conn:
            # Create table if not exists
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS kenpom_ratings (
                    team_name TEXT PRIMARY KEY,
                    rank INTEGER,
                    conference TEXT,
                    record TEXT,
                    adj_em REAL,
                    adj_o REAL,
                    adj_d REAL,
                    adj_t REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert/update teams
            for team in teams:
                _exec(conn, """
                    INSERT INTO kenpom_ratings 
                    (team_name, rank, conference, record, adj_em, adj_o, adj_d, adj_t)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (team_name) 
                    DO UPDATE SET
                        rank = EXCLUDED.rank,
                        conference = EXCLUDED.conference,
                        record = EXCLUDED.record,
                        adj_em = EXCLUDED.adj_em,
                        adj_o = EXCLUDED.adj_o,
                        adj_d = EXCLUDED.adj_d,
                        adj_t = EXCLUDED.adj_t,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    team['team'],
                    team['rank'],
                    team['conference'],
                    team['record'],
                    team['adj_em'],
                    team['adj_o'],
                    team['adj_d'],
                    team['adj_t']
                ))
            
            conn.commit()
            print(f"[KENPOM] Saved {len(teams)} teams to database")


# Example usage
if __name__ == "__main__":
    scraper = KenPomScraper()
    
    # Scrape homepage
    teams = scraper.scrape_homepage_rankings()
    
    if teams:
        print(f"\nTop 5 Teams:")
        for team in teams[:5]:
            print(f"{team['rank']}. {team['team']} - AdjEM: {team['adj_em']:.2f}")
        
        # Save to database
        scraper.save_to_database(teams)
        
        # Test lookup
        duke = scraper.get_team_by_name("Duke", teams)
        if duke:
            print(f"\nDuke Stats:")
            print(f"  Rank: #{duke['rank']}")
            print(f"  AdjEM: {duke['adj_em']:.2f}")
            print(f"  AdjO: {duke['adj_o']:.2f}")
            print(f"  AdjD: {duke['adj_d']:.2f}")
    else:
        print("\n[WARNING] No data scraped. KenPom may require login for full access.")
        print("[INFO] Consider using BartTorvik as free alternative.")
