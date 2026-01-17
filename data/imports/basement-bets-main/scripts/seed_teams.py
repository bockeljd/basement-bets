
import sys
import os
import datetime
from datetime import timedelta

# Ensure root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.parsers.espn_client import EspnClient
from src.parsers.epl_client import EplClient
from src.services.team_identity_service import TeamIdentityService

def seed_ncaam_nfl():
    espn = EspnClient()
    identity = TeamIdentityService()
    
    leagues = ['NFL', 'NCAAM']
    
    # Range: -14 days to +7 days
    today = datetime.date.today()
    start_date = today - timedelta(days=14)
    end_date = today + timedelta(days=7)
    
    for league in leagues:
        print(f"\n--- Seeding {league} ---")
        current = start_date
        while current <= end_date:
            date_str = current.strftime("%Y%m%d")
            # For NCAAM, groups=50 is handled implicitly if we fetch the standard scoreboard?
            # EspnClient currently fetches standard scoreboard.
            # User requirement: "groups=50 and limit=500" for NCAAM.
            # I might need to patch EspnClient to assume this or pass params.
            # For now, relying on default fetching which usually returns Top 25 + Conference logic unless 'limit' is high.
            # EspnClient.fetch_scoreboard sets limit=1000.
            
            # Note: The EspnClient implementation currently does NOT support passing custom params like 'groups'.
            # I will trust the default limit=1000 retrieves enough, or update client later if coverage is poor.
            
            # Pass groups=50 for NCAAM to ensure D1 coverage
            kwargs = {}
            if league == 'NCAAM':
                kwargs['groups'] = 50
                kwargs['limit'] = 500
                
            events = espn.fetch_scoreboard(league, date_str, **kwargs)
            print(f"Date {date_str}: Found {len(events)} events.")
            
            for ev in events:
                # Upsert Home
                try:
                    identity.get_or_create_team(
                        league=league,
                        provider="ESPN",
                        provider_team_id=ev['home_team_id'],
                        provider_team_name=ev['home_team']
                    )
                    # Upsert Away
                    identity.get_or_create_team(
                        league=league,
                        provider="ESPN",
                        provider_team_id=ev['away_team_id'],
                        provider_team_name=ev['away_team']
                    )
                except Exception as e:
                    print(f"Error seeding event {ev.get('id')}: {e}")

            current += timedelta(days=1)

def seed_epl():
    print("\n--- Seeding EPL ---")
    epl = EplClient()
    identity = TeamIdentityService()
    teams = epl.fetch_teams()
    
    for t in teams:
        tid = t['id']
        name = t['name']
        short = t.get('shortName')
        tla = t.get('tla')
        
        internal_id = identity.get_or_create_team(
            league="EPL",
            provider="FOOTBALL_DATA",
            provider_team_id=str(tid),
            provider_team_name=name,
            abbreviation=tla
        )
        # print(f"Mapped {name} -> {internal_id}")
    print(f"Seeded {len(teams)} EPL teams.")

if __name__ == "__main__":
    seed_ncaam_nfl() 
    seed_epl()
