import sys
import os
import json
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.services.grading_service import GradingService

def inspect_scores():
    service = GradingService()
    print('--- FETCHING RAW SCORES ---')
    # Use internal fetches to see raw data
    sport = 'basketball_ncaab'
    key = service._map_sport_to_key('NCAAM') # basketball_ncaab
    
    # Force fetch
    scores = service._fetch_scores(key, days=7)
    
    print(f"Scores Type: {type(scores)}")
    print(f"Count: {len(scores)}")
    
    if scores:
        print("First Item Keys:", scores[0].keys())
        print("First Item Sample:", json.dumps(scores[0], indent=2))
        
        # Check for 'completed' key in all items
        missing_completed = [s for s in scores if 'completed' not in s]
        if missing_completed:
            print(f"WARNING: {len(missing_completed)} items missing 'completed' key!")
            print("Sample Missing:", json.dumps(missing_completed[0], indent=2))
        else:
            print("All items have 'completed' key.")

if __name__ == "__main__":
    inspect_scores()
