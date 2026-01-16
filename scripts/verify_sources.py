import sys
import os
import json
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.models.odds_client import OddsAPIClient
from src.action_network import ActionNetworkClient

def verify_nfl_source():
    print("\n--- AUDIT: NFL SOURCE ---")
    
    # Check 1: Odds API
    odds_client = OddsAPIClient()
    print("Checking Odds API (americanfootball_nfl)...")
    try:
        odds = odds_client.get_odds('americanfootball_nfl')
        print(f"Odds API Count: {len(odds) if odds else 0}")
        if odds:
            print(f"Sample: {odds[0]['home_team']} vs {odds[0]['away_team']} ({odds[0]['commence_time']})")
    except Exception as e:
        print(f"Odds API Error: {e}")

    # Check 2: Action Network
    print("\nChecking Action Network (nfl)...")
    an_client = ActionNetworkClient()
    try:
        # Fetch for today/this week
        an_data = an_client.fetch_odds('nfl') 
        print(f"Action Network Count: {len(an_data) if an_data else 0}")
        if an_data:
             print(f"Sample: {an_data[0]['home_team']} vs {an_data[0]['away_team']} ({an_data[0]['commence_time']})")
             print(f"Raw Status: {an_data[0].get('status')}")
    except Exception as e:
        print(f"Action Network Error: {e}")

def verify_ncaam_source():
    print("\n--- AUDIT: NCAAM SOURCE ---")
    
    # Check 1: Odds API
    odds_client = OddsAPIClient()
    print("Checking Odds API (basketball_ncaab)...")
    try:
        odds = odds_client.get_odds('basketball_ncaab')
        print(f"Odds API Count: {len(odds) if odds else 0}")
        if odds:
             print(f"Sample: {odds[0]['home_team']} vs {odds[0]['away_team']} ({odds[0]['commence_time']})")
    except Exception as e:
        print(f"Odds API Error: {e}")

    # Check 2: Action Network
    print("\nChecking Action Network (ncaab)...")
    an_client = ActionNetworkClient()
    try:
        an_data = an_client.fetch_odds('ncaab')
        print(f"Action Network Count: {len(an_data) if an_data else 0}")
        if an_data:
             print(f"Sample: {an_data[0]['home_team']} vs {an_data[0]['away_team']} ({an_data[0]['commence_time']})")
    except Exception as e:
        print(f"Action Network Error: {e}")

if __name__ == "__main__":
    verify_nfl_source()
    verify_ncaam_source()
